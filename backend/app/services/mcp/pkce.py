"""PKCE (RFC 7636) verification helpers.

The MCP OAuth profile mandates PKCE — no exceptions for public clients.
We support the S256 method only; plain is explicitly forbidden by the MCP
spec for security reasons.
"""
from __future__ import annotations

import base64
import hashlib


_MIN_VERIFIER = 43
_MAX_VERIFIER = 128


class PKCEError(ValueError):
    """Surfaced to /token as `invalid_grant`."""


def verify(code_verifier: str, code_challenge: str, method: str = "S256") -> None:
    """Verify a code_verifier matches the stored challenge. Raises on mismatch.

    Per RFC 7636 §4.6:
      S256: BASE64URL(SHA256(ASCII(code_verifier))) == code_challenge
    """
    if method != "S256":
        raise PKCEError(
            f"Unsupported code_challenge_method: {method!r}. Only S256 PKCE is supported."
        )

    if not _MIN_VERIFIER <= len(code_verifier) <= _MAX_VERIFIER:
        raise PKCEError("code_verifier length out of range (must be 43-128 chars)")

    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    if expected != code_challenge:
        raise PKCEError("code_verifier does not match code_challenge")
