"""ATS integration error taxonomy. Raised by transports/providers; mapped to
HTTP responses in app/api/v2/core/error_handlers.py. Messages on these
exceptions are for SERVER-SIDE logs; the handlers return static client text."""


class AtsIntegrationError(Exception):
    """Base for all ATS integration failures."""


class AtsAuthError(AtsIntegrationError):
    """Provider rejected our credentials/integration (401/403)."""


class AtsNotSupportedError(AtsIntegrationError):
    """Operation not supported by the connected ATS (e.g. Workable job-create)."""


class AtsRateLimitedError(AtsIntegrationError):
    """Still rate-limited after bounded retries (429)."""


class AtsProviderError(AtsIntegrationError):
    """Provider 5xx / network failure / malformed response after retries."""


class AtsResourceNotFoundError(AtsIntegrationError):
    """The requested ATS resource does not exist."""


class AtsNotConnectedError(AtsIntegrationError):
    """The organization has no active ATS connection."""
