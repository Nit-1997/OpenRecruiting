"""Acquire raw JD text from a URL (SSRF-guarded) or an uploaded file.

This is the ONLY place that touches recruiter-supplied URLs/files. The URL path
is the SSRF-sensitive one: we require https, resolve the host ONCE to a concrete
IP, reject any private / loopback / link-local / reserved / cloud-metadata
address, then make httpx connect to THAT pinned IP — so a DNS-rebinding attacker
cannot return a public IP to the validator and a private IP to the connect. The
original hostname is preserved in the Host header (origin routing) and the TLS
SNI extension (cert verification), so legitimate https hosts still verify. Every
redirect hop is re-resolved + re-pinned. Heavy parsers (bs4/pypdf/docx) are
imported lazily so the SSRF guard + sanitizer stay importable without them.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from io import BytesIO
from urllib.parse import urljoin, urlparse, urlunparse

import structlog

logger = structlog.get_logger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


def find_first_url(text: str) -> str | None:
    """Return the first http(s) URL in free text, trimming trailing punctuation."""
    if not text:
        return None
    m = _URL_RE.search(text)
    if not m:
        return None
    return m.group(0).rstrip(".,;:!?")

ALLOWED_SCHEMES = {"https"}
ALLOWED_CONTENT_PREFIXES = ("text/html", "application/xhtml", "text/plain")
URL_MAX_BYTES = 2_000_000
FILE_MAX_BYTES = 5_000_000
MAX_REDIRECTS = 2
TIMEOUT_S = 5.0
_USER_AGENT = "OpenRecruitingIntakeBot/1.0 (+http://localhost:3000)"


class JdFetchError(Exception):
    """Base — could not obtain JD text from the source."""


class SsrfBlockedError(JdFetchError):
    """The URL is not allowed (bad scheme, unresolvable, or private/internal target)."""


class UnsupportedFileError(JdFetchError):
    """File/content type we don't parse."""


class FileTooLargeError(JdFetchError):
    """Source exceeded the size cap."""


def _ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    # is_link_local covers 169.254.0.0/16 (incl. the 169.254.169.254 cloud
    # metadata endpoint) and fe80::/10. The rest block RFC1918, loopback,
    # CGNAT-ish reserved, multicast, and unspecified.
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_and_validate(host: str) -> str:
    """Resolve `host` ONCE and return a single concrete IP that passed validation.

    Every resolved address must be public — if any is private/loopback/etc. we
    reject (a multi-record name with one bad answer is treated as hostile). The
    returned IP is the one the caller pins the connection to, so the connect can
    never re-resolve to a different (private) address.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SsrfBlockedError("could not resolve host") from exc
    if not infos:
        raise SsrfBlockedError("could not resolve host")
    pinned: str | None = None
    for info in infos:
        ip_str = info[4][0]
        if _ip_blocked(ip_str):
            raise SsrfBlockedError("URL resolves to a disallowed address")
        if pinned is None:
            pinned = ip_str
    assert pinned is not None  # non-empty infos with no blocked IP ⇒ pinned set
    return pinned


def _validated_host(url: str) -> str:
    """Parse + scheme/host-check `url`; return its hostname (no DNS yet)."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SsrfBlockedError("only https URLs are allowed")
    host = parsed.hostname
    if not host:
        raise SsrfBlockedError("URL is missing a host")
    return host


def _pin_url_to_ip(url: str, ip: str) -> str:
    """Rewrite `url` so the connection target host is the literal `ip`, keeping
    scheme/port/path/query. IPv6 literals are bracketed."""
    parsed = urlparse(url)
    literal = f"[{ip}]" if ":" in ip else ip
    netloc = f"{literal}:{parsed.port}" if parsed.port else literal
    return urlunparse(parsed._replace(netloc=netloc))


def validate_url(url: str) -> str:
    """Raise SsrfBlockedError unless `url` is an https URL resolving to a public host."""
    _resolve_and_validate(_validated_host(url))
    return url


def _looks_like_html(ctype: str, sample: str) -> bool:
    return ctype.startswith(("text/html", "application/xhtml")) or "<html" in sample[:2000].lower()


async def fetch_url_text(url: str, *, client: object | None = None) -> str:
    """Fetch `url` (SSRF-guarded, manual redirects, size-capped) → extracted text.

    DNS-rebinding-safe: each hop resolves the host ONCE, validates the IP, then
    connects to THAT pinned IP. The hostname rides along in the Host header
    (origin routing) and the `sni_hostname` TLS extension (cert verification),
    so the connection cannot be re-pointed at a private address between the
    validation and the connect.
    """
    import httpx

    current = url
    host = _validated_host(current)
    pinned_ip = _resolve_and_validate(host)
    owns_client = client is None
    cl = client or httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False)
    try:
        for _ in range(MAX_REDIRECTS + 1):
            connect_url = _pin_url_to_ip(current, pinned_ip)
            async with cl.stream(
                "GET",
                connect_url,
                headers={"User-Agent": _USER_AGENT, "Host": host},
                extensions={"sni_hostname": host},
            ) as resp:
                if resp.is_redirect:
                    loc = resp.headers.get("location")
                    if not loc:
                        raise JdFetchError("redirect without a location")
                    current = urljoin(current, loc)
                    host = _validated_host(current)
                    pinned_ip = _resolve_and_validate(host)
                    continue
                ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                if ctype and not ctype.startswith(ALLOWED_CONTENT_PREFIXES):
                    raise UnsupportedFileError(f"unsupported content-type: {ctype}")
                total = 0
                chunks: list[bytes] = []
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > URL_MAX_BYTES:
                        raise FileTooLargeError("page exceeds size cap")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                text = raw.decode(resp.encoding or "utf-8", errors="replace")
                return extract_text_from_html(text) if _looks_like_html(ctype, text) else text
        raise JdFetchError("too many redirects")
    finally:
        if owns_client:
            await cl.aclose()  # type: ignore[union-attr]


def extract_text_from_html(html: str) -> str:
    """Strip chrome/scripts and return the visible text. Lazy bs4 import."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "svg"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def parse_file(filename: str | None, content_type: str | None, data: bytes) -> str:
    """Extract text from an uploaded pdf / docx / txt|md file. Lazy heavy imports."""
    if len(data) > FILE_MAX_BYTES:
        raise FileTooLargeError("file exceeds size cap")
    name = (filename or "").lower()
    ctype = (content_type or "").lower()

    if name.endswith((".txt", ".md")) or ctype.startswith("text/"):
        return data.decode("utf-8", errors="replace")

    if name.endswith(".pdf") or "pdf" in ctype:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)

    if name.endswith(".docx") or "word" in ctype or "officedocument" in ctype:
        import docx

        document = docx.Document(BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs)

    raise UnsupportedFileError(f"unsupported file type: {name or ctype or 'unknown'}")
