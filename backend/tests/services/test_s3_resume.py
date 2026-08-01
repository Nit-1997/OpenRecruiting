from app.services import s3_service


class _Settings:
    def __init__(self, bucket):
        self.S3_RESUME_BUCKET = bucket
        self.AWS_REGION = "us-west-1"


def test_no_bucket_returns_none(monkeypatch):
    monkeypatch.setattr(s3_service, "get_settings", lambda: _Settings(""))
    assert s3_service.upload_resume(b"data", "c1", "r.pdf") is None


def test_uploads_and_returns_url(monkeypatch):
    calls: dict = {}

    class _FakeS3:
        def put_object(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr(s3_service, "get_settings", lambda: _Settings("mybucket"))
    monkeypatch.setattr(s3_service, "get_s3_client", lambda: _FakeS3())

    url = s3_service.upload_resume(b"data", "c1", "Resume.pdf")
    assert url == "https://mybucket.s3.us-west-1.amazonaws.com/resumes/c1/Resume.pdf"
    assert calls["Bucket"] == "mybucket"
    assert calls["ContentType"] == "application/pdf"
    assert calls["Key"] == "resumes/c1/Resume.pdf"
