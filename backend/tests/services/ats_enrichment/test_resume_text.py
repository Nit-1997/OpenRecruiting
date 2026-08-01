"""fetch_resume_text: bounded download + parse, fail-soft. Uses respx to mock the
(presigned) URL. Text path exercises parse_file's .txt branch end-to-end."""

import httpx

from app.services.ats_enrichment.resume_text import (
    _filename_from_url,
    fetch_resume_text,
)

URL = "https://workablehr.s3.amazonaws.com/uploads/x/Jane_Resume.txt?X-Amz-Expires=60000"


def test_filename_from_url_strips_query():
    assert _filename_from_url(URL) == "Jane_Resume.txt"


async def test_reads_text_resume(respx_mock):
    respx_mock.get(URL).mock(
        return_value=httpx.Response(
            200, content=b"Jane Doe\nSenior Financial Analyst\nFP&A, SQL",
            headers={"content-type": "text/plain"},
        )
    )
    text = await fetch_resume_text(URL, max_bytes=1_000_000)
    assert text is not None and "Senior Financial Analyst" in text


async def test_oversize_returns_none(respx_mock):
    respx_mock.get(URL).mock(
        return_value=httpx.Response(
            200, content=b"x" * 500, headers={"content-type": "text/plain"}
        )
    )
    assert await fetch_resume_text(URL, max_bytes=100) is None


async def test_http_error_returns_none(respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(404))
    assert await fetch_resume_text(URL, max_bytes=1_000_000) is None
