from app.services.email.base import EmailProvider, EmailMessage, EmailResult
from app.services.email.zoho_provider import ZohoEmailProvider, get_email_provider
from app.services.email.resend_provider import ResendEmailProvider
from app.services.email.service import EmailService, get_email_service

__all__ = [
    "EmailProvider",
    "EmailMessage",
    "EmailResult",
    "ZohoEmailProvider",
    "ResendEmailProvider",
    "get_email_provider",
    "EmailService",
    "get_email_service",
]
