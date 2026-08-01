from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class EmailMessage:
    to_email: str
    to_name: Optional[str]
    subject: str
    html_body: str
    text_body: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    reply_to: Optional[str] = None


@dataclass
class EmailResult:
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


class EmailProvider(ABC):
    @abstractmethod
    async def send_email(self, message: EmailMessage) -> EmailResult:
        """Send a single email. Returns result with success/failure info."""
        pass

    @abstractmethod
    async def send_batch(self, messages: list[EmailMessage]) -> list[EmailResult]:
        """Send multiple emails. Returns results for each message."""
        pass
