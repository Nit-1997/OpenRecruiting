from functools import lru_cache
import httpx

from app.config import get_settings
from app.logging_config import get_logger
from app.services.supabase import get_async_http_client
from app.services.email.base import EmailProvider, EmailMessage, EmailResult

logger = get_logger(__name__)


class ZohoEmailProvider(EmailProvider):
    def __init__(self, api_token: str, from_email: str, from_name: str, base_url: str):
        self.api_token = api_token
        self.from_email = from_email
        self.from_name = from_name
        self.base_url = base_url

    async def send_email(self, message: EmailMessage) -> EmailResult:
        client = get_async_http_client()
        headers = {
            "Authorization": f"Zoho-enczapikey {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "from": {
                "address": message.from_email or self.from_email,
                "name": message.from_name or self.from_name,
            },
            "to": [{
                "email_address": {
                    "address": message.to_email,
                    "name": message.to_name or "",
                }
            }],
            "subject": message.subject,
            "htmlbody": message.html_body,
        }

        if message.text_body:
            payload["textbody"] = message.text_body
        if message.reply_to:
            payload["reply_to"] = [{"address": message.reply_to}]

        try:
            response = await client.post(
                f"{self.base_url}/email",
                json=payload,
                headers=headers,
            )
        except httpx.RequestError as e:
            logger.error(f"Email: Request failed: {e}")
            return EmailResult(success=False, error=f"Request failed: {str(e)}")

        if response.status_code in (200, 201):
            data = response.json()
            request_id = data.get("request_id")
            logger.info(f"Email: Sent successfully to {message.to_email}, request_id={request_id}")
            return EmailResult(success=True, message_id=request_id)
        else:
            try:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", "Unknown error")
                error_code = error_data.get("error", {}).get("code", "")
                logger.error(f"Email: ZeptoMail error {error_code}: {error_msg}")
                return EmailResult(success=False, error=f"{error_code}: {error_msg}")
            except Exception:
                logger.error(f"Email: HTTP {response.status_code}")
                return EmailResult(success=False, error=f"HTTP {response.status_code}")

    async def send_batch(self, messages: list[EmailMessage]) -> list[EmailResult]:
        results = []
        for message in messages:
            result = await self.send_email(message)
            results.append(result)
        return results


@lru_cache()
def get_email_provider() -> EmailProvider:
    settings = get_settings()
    provider_type = settings.EMAIL_PROVIDER.lower()

    if provider_type == "zoho":
        if not settings.ZEPTOMAIL_API_TOKEN:
            raise ValueError("ZEPTOMAIL_API_TOKEN not configured")
        return ZohoEmailProvider(
            api_token=settings.ZEPTOMAIL_API_TOKEN,
            from_email=settings.EMAIL_FROM_ADDRESS,
            from_name=settings.EMAIL_FROM_NAME,
            base_url=settings.ZEPTOMAIL_BASE_URL,
        )
    elif provider_type == "resend":
        from app.services.email.resend_provider import ResendEmailProvider
        if not settings.RESEND_API_KEY:
            raise ValueError("RESEND_API_KEY not configured")
        return ResendEmailProvider(
            api_key=settings.RESEND_API_KEY,
            from_email=settings.EMAIL_FROM_ADDRESS,
            from_name=settings.EMAIL_FROM_NAME,
        )
    elif provider_type == "sendgrid":
        raise NotImplementedError("SendGrid provider not yet implemented")
    elif provider_type == "postmark":
        raise NotImplementedError("Postmark provider not yet implemented")
    else:
        raise ValueError(f"Unknown email provider: {provider_type}")
