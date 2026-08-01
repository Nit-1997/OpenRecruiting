"""Extra coverage for s3_service.upload_blog_image (happy path + guard branches)
and sqs_publisher.publish_event (ClientError branch). The module-scope client
cache + the offload-to-thread behavior are already covered by test_aws_offload.py;
this fills the remaining branches.
"""
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import app.services.s3_service as s3
import app.services.sqs_publisher as sqs


@pytest.fixture(autouse=True)
def _reset_s3_client():
    s3._s3_client = None
    yield
    s3._s3_client = None


def _s3_settings(bucket="blog-bucket"):
    settings = MagicMock()
    settings.AWS_REGION = "us-west-1"
    settings.AWS_ACCESS_KEY_ID = "k"
    settings.AWS_SECRET_ACCESS_KEY = "s"
    settings.S3_BLOG_BUCKET = bucket
    return settings


def test_upload_blog_image_happy_path_returns_url():
    fake_client = MagicMock()
    with patch.object(s3, "boto3") as mock_boto, \
         patch.object(s3, "get_settings", return_value=_s3_settings()):
        mock_boto.client.return_value = fake_client
        url = s3.upload_blog_image(b"\x89PNG", "my photo!.png", "image/png")
    assert url.startswith("https://blog-bucket.s3.us-west-1.amazonaws.com/blog/")
    # filename sanitized (space + ! -> underscore) and capped.
    assert "my_photo_.png" in url
    fake_client.put_object.assert_called_once()


def test_upload_blog_image_rejects_oversize():
    big = b"x" * (s3.MAX_FILE_SIZE + 1)
    with pytest.raises(ValueError, match="exceeds 5MB"):
        s3.upload_blog_image(big, "f.png", "image/png")


def test_upload_blog_image_rejects_missing_bucket():
    with patch.object(s3, "boto3"), \
         patch.object(s3, "get_settings", return_value=_s3_settings(bucket="")):
        with pytest.raises(ValueError, match="S3_BLOG_BUCKET not configured"):
            s3.upload_blog_image(b"x", "f.png", "image/png")


def test_sanitize_filename_strips_and_caps():
    name = s3.sanitize_filename("a b/c?.png" + "z" * 200)
    assert "/" not in name and " " not in name and "?" not in name
    assert len(name) <= 100


async def test_publish_event_returns_false_on_client_error():
    fake_client = MagicMock()
    fake_client.send_message.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "no"}}, "SendMessage"
    )
    settings = MagicMock()
    settings.SQS_QUEUE_URL = "https://sqs.local/q.fifo"
    settings.SQS_REGION = "us-west-1"
    with patch.object(sqs, "_get_sqs_client", return_value=fake_client), \
         patch.object(sqs, "get_settings", return_value=settings):
        ok = await sqs.publish_event("evt", {"organization_id": "o1"})
    assert ok is False


def test_get_sqs_client_caches():
    sqs._sqs_client = None
    settings = MagicMock()
    settings.SQS_REGION = "us-west-1"
    try:
        with patch.object(sqs, "boto3") as mock_boto, \
             patch.object(sqs, "get_settings", return_value=settings):
            mock_boto.client.return_value = MagicMock()
            a = sqs._get_sqs_client()
            b = sqs._get_sqs_client()
        assert a is b
        mock_boto.client.assert_called_once()
    finally:
        sqs._sqs_client = None
