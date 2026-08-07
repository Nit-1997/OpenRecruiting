from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    domain: Optional[str] = Field(None, max_length=255)


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    domain: Optional[str] = None
    description: Optional[str] = None
    auto_join_enabled: Optional[bool] = None
    auto_join_untracked: Optional[bool] = None
    blocked_domains: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OrganizationListResponse(BaseModel):
    organizations: list[OrganizationResponse]
    total: int
