from fastapi import APIRouter, HTTPException, status
from app.models.blog import BlogPostResponse, BlogPostListResponse
from app.services.supabase import get_supabase_admin_client

router = APIRouter(prefix="/public/blog", tags=["Public - Blog"])


def _build_search_or_filter(search: str) -> str:
    """Build a safe PostgREST `or=` ilike filter from raw user input.

    The raw `search` string is otherwise interpolated straight into PostgREST's
    `or=` grammar, where `,` separates conditions, `(`/`)` group them, and `.`
    forms operator paths — so unescaped input can break out and inject
    arbitrary filters. PostgREST treats a value as a literal when it is wrapped
    in double quotes; inside the quotes only `"` and `\\` are special, so we
    backslash-escape those and quote the whole pattern. The `*` ilike wildcards
    stay outside the quotes to remain operative.
    """
    escaped = search.replace("\\", "\\\\").replace('"', '\\"')
    pattern = f'"*{escaped}*"'
    return f"title.ilike.{pattern},excerpt.ilike.{pattern}"


@router.get("/posts", response_model=BlogPostListResponse)
async def list_published_posts(
    page: int = 1,
    page_size: int = 12,
    search: str = "",
    sort: str = "latest",
):
    supabase = get_supabase_admin_client()
    offset = (page - 1) * page_size

    count_query = supabase.table("blog_posts") \
        .select("id") \
        .eq("status", "published")

    query = supabase.table("blog_posts") \
        .select("*") \
        .eq("status", "published")

    if search:
        or_cond = _build_search_or_filter(search)
        count_query = count_query.or_filter(or_cond)
        query = query.or_filter(or_cond)

    total = await count_query.count_async()

    if sort == "oldest":
        query = query.order("created_at", desc=False)
    elif sort == "top":
        query = query.order("likes", desc=True)
    else:
        query = query.order("created_at", desc=True)

    result = await query \
        .limit(page_size) \
        .offset(offset) \
        .execute_async()

    posts = [BlogPostResponse(**p) for p in (result.data or [])]
    return BlogPostListResponse(posts=posts, total=total, page=page, page_size=page_size)


@router.get("/posts/{slug}", response_model=BlogPostResponse)
async def get_published_post(slug: str):
    supabase = get_supabase_admin_client()
    result = await supabase.table("blog_posts") \
        .select("*") \
        .eq("slug", slug) \
        .eq("status", "published") \
        .single() \
        .execute_async()

    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")
    return BlogPostResponse(**result.data)


@router.post("/posts/{slug}/like")
async def like_post(slug: str):
    supabase = get_supabase_admin_client()
    result = await supabase.rpc("increment_blog_likes", {"post_slug": slug})
    if result.data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")
    likes = result.data
    if isinstance(likes, list) and len(likes) > 0:
        likes = likes[0]
    return {"likes": likes}
