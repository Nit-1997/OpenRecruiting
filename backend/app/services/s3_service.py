import time
import re
import boto3
from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# Module-scope boto3 S3 client (sync, thread-safe). Previously constructed on
# every upload. A process-wide singleton is correct (NOT a loop-bound async
# resource). BE-A1.
#
# NOTE: upload_blog_image stays synchronous because its only caller
# (admin/blog_posts.py:132) invokes it without `await`, and that router file is
# out of BE-A1 scope. Threadpool offload of put_object would require making the
# helper async + editing that forbidden call site — tracked as follow-up.
_s3_client = None


def get_s3_client():
    global _s3_client
    if _s3_client is None:
        settings = get_settings()
        _s3_client = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
    return _s3_client


def sanitize_filename(filename: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
    return name[:100]


def upload_blog_image(file_bytes: bytes, filename: str, content_type: str) -> str:
    if not content_type.startswith("image/"):
        raise ValueError("Only image files are allowed")

    if len(file_bytes) > MAX_FILE_SIZE:
        raise ValueError("File size exceeds 5MB limit")

    settings = get_settings()
    bucket = settings.S3_BLOG_BUCKET
    if not bucket:
        raise ValueError("S3_BLOG_BUCKET not configured")

    safe_name = sanitize_filename(filename)
    key = f"blog/{int(time.time())}-{safe_name}"

    s3 = get_s3_client()
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=file_bytes,
        ContentType=content_type,
    )

    url = f"https://{bucket}.s3.{settings.AWS_REGION}.amazonaws.com/{key}"
    logger.info(f"Uploaded blog image: {key}")
    return url


def upload_resume(
    file_bytes: bytes, candidate_id: str, filename: str | None
) -> str | None:
    """Copy a downloaded resume to durable storage so candidates.resume_url
    survives the ATS's expiring presigned link. Returns None when no resume
    bucket is configured (enrichment keeps the extracted signal regardless).
    Synchronous (boto3) — call via asyncio.to_thread from the async worker."""
    settings = get_settings()
    bucket = settings.S3_RESUME_BUCKET
    if not bucket:
        return None
    safe_name = sanitize_filename(filename or "resume.pdf")
    content_type = (
        "application/pdf"
        if safe_name.lower().endswith(".pdf")
        else "application/octet-stream"
    )
    key = f"resumes/{candidate_id}/{safe_name}"
    s3 = get_s3_client()
    s3.put_object(
        Bucket=bucket, Key=key, Body=file_bytes, ContentType=content_type
    )
    url = f"https://{bucket}.s3.{settings.AWS_REGION}.amazonaws.com/{key}"
    logger.info(f"Uploaded resume: {key}")
    return url
