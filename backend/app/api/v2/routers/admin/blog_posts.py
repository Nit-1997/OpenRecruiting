import asyncio
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from datetime import datetime, timezone
from app.dependencies import require_staff, CurrentUser
from app.models.blog import BlogPostCreate, BlogPostUpdate, BlogPostResponse, BlogPostListResponse, ImageUploadResponse
from app.services.supabase import get_supabase_admin_client
from app.services.s3_service import upload_blog_image

router = APIRouter(prefix="/blog-posts", tags=["Admin - Blog Posts"])


@router.post("", response_model=BlogPostResponse, status_code=status.HTTP_201_CREATED)
async def create_blog_post(
    post: BlogPostCreate,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()

    existing = await supabase.table("blog_posts") \
        .select("id") \
        .eq("slug", post.slug) \
        .execute_async()
    if existing.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "A post with this slug already exists")

    data = post.model_dump()
    data["author_id"] = str(current_user.id)

    result = await supabase.table("blog_posts") \
        .insert(data) \
        .execute_async()
    row = result.data[0] if isinstance(result.data, list) else result.data
    return BlogPostResponse(**row)


@router.get("", response_model=BlogPostListResponse)
async def list_blog_posts(
    page: int = 1,
    page_size: int = 20,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    offset = (page - 1) * page_size

    total = await supabase.table("blog_posts") \
        .select("id") \
        .count_async()

    result = await supabase.table("blog_posts") \
        .select("*") \
        .order("created_at", desc=True) \
        .limit(page_size) \
        .offset(offset) \
        .execute_async()

    posts = [BlogPostResponse(**p) for p in (result.data or [])]
    return BlogPostListResponse(posts=posts, total=total, page=page, page_size=page_size)


@router.get("/{slug}", response_model=BlogPostResponse)
async def get_blog_post(
    slug: str,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    result = await supabase.table("blog_posts") \
        .select("*") \
        .eq("slug", slug) \
        .single() \
        .execute_async()

    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")
    return BlogPostResponse(**result.data)


@router.put("/{slug}", response_model=BlogPostResponse)
async def update_blog_post(
    slug: str,
    post: BlogPostUpdate,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    update_data = post.model_dump(exclude_none=True)
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    if "slug" in update_data and update_data["slug"] != slug:
        existing = await supabase.table("blog_posts") \
            .select("id") \
            .eq("slug", update_data["slug"]) \
            .execute_async()
        if existing.data:
            raise HTTPException(status.HTTP_409_CONFLICT, "A post with this slug already exists")

    result = await supabase.table("blog_posts") \
        .update(update_data) \
        .eq("slug", slug) \
        .execute_async()

    data = result.data
    if not data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")
    row = data[0] if isinstance(data, list) else data
    return BlogPostResponse(**row)


@router.delete("/{slug}")
async def delete_blog_post(
    slug: str,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    await supabase.table("blog_posts") \
        .delete() \
        .eq("slug", slug) \
        .execute_async()
    return {"message": "Post deleted", "slug": slug}


@router.post("/upload-image", response_model=ImageUploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_staff),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only image files are allowed")

    file_bytes = await file.read()
    if len(file_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File size exceeds 5MB limit")

    try:
        # boto3 S3 put_object is sync — offload so a multi-MB upload doesn't
        # block the event loop (and every other concurrent request) on the PUT.
        url = await asyncio.to_thread(
            upload_blog_image, file_bytes, file.filename or "image.png", file.content_type
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    return ImageUploadResponse(url=url)
