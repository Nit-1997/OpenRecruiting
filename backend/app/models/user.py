from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(default="recruiter", pattern="^(owner|admin|recruiter|viewer)$")


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None
    organization_id: Optional[UUID] = None
    role: Optional[str] = None
    is_staff: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None
    invitation_status: str = "invited"
    invitation_sent_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int


class MagicLinkResponse(BaseModel):
    message: str
    user_id: UUID
    email: str


class ResendMagicLinkRequest(BaseModel):
    email: EmailStr


class DeleteUserResponse(BaseModel):
    message: str
    user_id: UUID


class OTPVerifyRequest(BaseModel):
    email: EmailStr
    token: str = Field(..., min_length=6, max_length=8)


class OTPVerifyResponse(BaseModel):
    message: str
    access_token: str
    refresh_token: str
    user_id: UUID


class ResendOTPRequest(BaseModel):
    email: EmailStr


class ResendOTPResponse(BaseModel):
    message: str
    email: str


class CompleteOnboardingResponse(BaseModel):
    message: str
    onboarding_completed: bool
