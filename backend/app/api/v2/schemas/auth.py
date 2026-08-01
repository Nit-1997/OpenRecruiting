"""
Auth schemas for `/api/v2/auth/me`.

The frontend talks to Supabase Auth directly via `@supabase/supabase-js`; the
v2 backend only verifies the resulting bearer token and exposes this small
profile-join helper.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr


class MeResponse(BaseModel):
    id: UUID
    email: EmailStr
    organization_id: Optional[UUID] = None
    is_staff: bool
    name: Optional[str] = None
    has_pending_invite: bool = False


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    token: str


class VerifyOtpResponse(BaseModel):
    access_token: str
    refresh_token: str
