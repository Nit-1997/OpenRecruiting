import httpx

from app.logging_config import get_logger
from app.services.supabase import get_async_http_client
from app.services.email.base import EmailProvider, EmailMessage, EmailResult

logger = get_logger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class ResendEmailProvider(EmailProvider):
    def __init__(self, api_key: str, from_email: str, from_name: str):
        self.api_key = api_key
        self.from_email = from_email
        self.from_name = from_name

    async def send_email(self, message: EmailMessage) -> EmailResult:
        client = get_async_http_client()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        from_addr = message.from_email or self.from_email
        from_name = message.from_name or self.from_name
        payload = {
            "from": f"{from_name} <{from_addr}>",
            "to": [message.to_email],
            "subject": message.subject,
            "html": message.html_body,
        }

        if message.text_body:
            payload["text"] = message.text_body
        if message.reply_to:
            payload["reply_to"] = message.reply_to

        try:
            response = await client.post(
                RESEND_API_URL,
                json=payload,
                headers=headers,
            )
        except httpx.RequestError as e:
            logger.error(f"Email: Resend request failed: {e}")
            return EmailResult(success=False, error=f"Request failed: {str(e)}")

        if response.status_code == 200:
            data = response.json()
            msg_id = data.get("id")
            logger.info(f"Email: Sent via Resend to {message.to_email}, id={msg_id}")
            return EmailResult(success=True, message_id=msg_id)
        else:
            try:
                error_data = response.json()
                error_name = error_data.get("name", "")
                error_msg = error_data.get("message", "Unknown error")
                logger.error(f"Email: Resend error {error_name}: {error_msg}")
                return EmailResult(success=False, error=f"{error_name}: {error_msg}")
            except Exception:
                logger.error(f"Email: Resend HTTP {response.status_code}")
                return EmailResult(success=False, error=f"HTTP {response.status_code}")

    async def send_batch(self, messages: list[EmailMessage]) -> list[EmailResult]:
        results = []
        for message in messages:
            result = await self.send_email(message)
            results.append(result)
        return results
