"""Characterization tests for jd_fetch helpers not yet covered:
_pin_url_to_ip, _looks_like_html, extract_text_from_html, parse_file.
"""

import pytest

from app.services.intake.jd_fetch import (
    FileTooLargeError,
    UnsupportedFileError,
    _looks_like_html,
    _pin_url_to_ip,
    extract_text_from_html,
    parse_file,
)


def test_pin_url_to_ip_ipv4():
    out = _pin_url_to_ip("https://example.com/jobs?x=1", "1.2.3.4")
    assert out == "https://1.2.3.4/jobs?x=1"


def test_pin_url_to_ip_ipv4_with_port():
    out = _pin_url_to_ip("https://example.com:8443/p", "1.2.3.4")
    assert "1.2.3.4:8443" in out


def test_pin_url_to_ip_ipv6_bracketed():
    out = _pin_url_to_ip("https://example.com/p", "::1")
    assert "[::1]" in out


def test_looks_like_html_by_content_type():
    assert _looks_like_html("text/html", "") is True
    assert _looks_like_html("application/xhtml+xml", "") is True


def test_looks_like_html_by_body_sniff():
    assert _looks_like_html("text/plain", "<HTML><body>hi") is True


def test_looks_like_html_plain_text():
    assert _looks_like_html("text/plain", "just plain text") is False


def test_extract_text_from_html_strips_chrome():
    html = "<html><head><style>x{}</style></head><body><nav>menu</nav><p>Real content</p><footer>foot</footer></body></html>"
    out = extract_text_from_html(html)
    assert "Real content" in out
    assert "menu" not in out
    assert "foot" not in out


def test_parse_file_txt():
    assert parse_file("jd.txt", "text/plain", b"hello jd") == "hello jd"


def test_parse_file_text_by_content_type():
    assert parse_file(None, "text/markdown", b"# Role") == "# Role"


def test_parse_file_too_large():
    from app.services.intake import jd_fetch
    big = b"x" * (jd_fetch.FILE_MAX_BYTES + 1)
    with pytest.raises(FileTooLargeError):
        parse_file("jd.txt", "text/plain", big)


def test_parse_file_unsupported_type():
    with pytest.raises(UnsupportedFileError):
        parse_file("jd.exe", "application/octet-stream", b"\x00\x01")
