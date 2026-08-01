from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional


class BlogPostCreate(BaseModel):
    title: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    excerpt: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    thumbnail_url: Optional[str] = None
    hero_image_url: Optional[str] = None
    author_name: str = Field(default="OpenRecruiting Team")
    author_avatar: Optional[str] = None
    tags: list[str] = []
    status: str = Field(default="draft")


class BlogPostUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    excerpt: Optional[str] = None
    content: Optional[str] = None
    thumbnail_url: Optional[str] = None
    hero_image_url: Optional[str] = None
    author_name: Optional[str] = None
    author_avatar: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = None


class BlogPostResponse(BaseModel):
    id: UUID
    slug: str
    title: str
    excerpt: str
    content: str
    thumbnail_url: Optional[str] = None
    hero_image_url: Optional[str] = None
    author_name: str
    author_avatar: Optional[str] = None
    author_id: Optional[UUID] = None
    tags: list[str] = []
    likes: int = 0
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "extra": "ignore"}


class BlogPostListResponse(BaseModel):
    posts: list[BlogPostResponse]
    total: int
    page: int
    page_size: int


class ImageUploadResponse(BaseModel):
    url: str
