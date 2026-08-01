from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional


class PromotionCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    percent_off: int = Field(..., ge=0, le=100)
    is_active: bool = True
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class PromotionUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    percent_off: Optional[int] = Field(None, ge=0, le=100)
    is_active: Optional[bool] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class PromotionResponse(BaseModel):
    id: UUID
    code: str
    percent_off: int
    is_active: bool
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "extra": "ignore"}
