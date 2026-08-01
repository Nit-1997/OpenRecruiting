"""Recording / transcript response schemas (kept lightweight — the endpoints
currently return plain dicts; this module exists to allow future tightening
without touching routers)."""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class RecordingUrlResponse(BaseModel):
    url: str
    expires_at: datetime


class TranscriptResponse(BaseModel):
    segments: List[Any] = []
    duration_seconds: Optional[float] = None
    word_count: Optional[int] = None
