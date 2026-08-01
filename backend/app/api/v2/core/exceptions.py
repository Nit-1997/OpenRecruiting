"""
v2 domain exceptions.

Services raise these; the FastAPI exception handlers in `error_handlers.py`
map them to HTTP responses. Routes never construct HTTPException directly —
that responsibility lives one layer above (services) or one layer below
(handlers).
"""

from typing import Optional


class V2DomainError(Exception):
    """Base class for all v2 domain errors."""


class NotFoundError(V2DomainError):
    """Resource not found (404)."""


class ConflictError(V2DomainError):
    """State-conflict error (409). `code` is a stable machine-readable code
    e.g. 'LAST_ROUND', 'REQ_CLOSED'; `detail` is the human message."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ForbiddenError(V2DomainError):
    """Access denied (403)."""


class ValidationError(V2DomainError):
    """Bad request payload / invalid input (400)."""


class PreconditionFailedError(V2DomainError):
    """If-Match stale (412)."""


class PreconditionRequiredError(V2DomainError):
    """If-Match header missing (428)."""


class UpstreamServiceError(V2DomainError):
    """Recall.ai / Lambda / other external dependency failed (502)."""

    def __init__(self, detail: str, *, status_code: int = 502):
        super().__init__(detail)
        self.status_code = status_code


class NotImplementedFeatureError(V2DomainError):
    """Code path intentionally not implemented yet (501)."""
