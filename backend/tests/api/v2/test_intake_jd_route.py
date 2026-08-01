"""Tests for POST /api/v2/intake/jd/extract.

The router validates "at least one of text/file", reads settings.INTAKE_JD_MODEL,
calls extract_jd, and maps the jd_fetch exception hierarchy onto HTTP codes. We
override the anthropic client dependency and patch extract_jd so no network/LLM
is touched.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_anthropic_async_client
from app.main import app
from app.services.intake.jd_fetch import (
    FileTooLargeError,
    JdFetchError,
    SsrfBlockedError,
    UnsupportedFileError,
)

ENDPOINT = "/api/v2/intake/jd/extract"


@pytest.fixture
def client():
    app.dependency_overrides[get_anthropic_async_client] = lambda: object()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def test_no_input_400(recruiter_client):
    # recruiter_client already overrides auth; reuse it but post nothing useful.
    resp = recruiter_client.post(ENDPOINT, data={})
    assert resp.status_code == 400
    assert "Paste" in resp.json()["detail"]


def _ok_result():
    return {"status": "ok", "source": "text", "formatted_jd": "JD here", "structured": None}


def test_text_extract_ok(recruiter_client):
    with patch("app.api.v2.routers.intake_jd.extract_jd", AsyncMock(return_value=_ok_result())):
        resp = recruiter_client.post(ENDPOINT, data={"text": "Senior Engineer in NYC"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["formatted_jd"] == "JD here"


def test_file_extract_reads_bytes(recruiter_client):
    captured = {}

    async def fake_extract(client, model, text, file):
        captured["file"] = file
        captured["text"] = text
        return {"status": "ok", "source": "file", "formatted_jd": "from file"}

    with patch("app.api.v2.routers.intake_jd.extract_jd", fake_extract):
        resp = recruiter_client.post(
            ENDPOINT,
            files={"file": ("jd.txt", b"job description bytes", "text/plain")},
        )
    assert resp.status_code == 200
    assert resp.json()["source"] == "file"
    # file_arg is (filename, content_type, bytes)
    assert captured["file"][0] == "jd.txt"
    assert captured["file"][2] == b"job description bytes"
    assert captured["text"] is None


@pytest.mark.parametrize("exc,code", [
    (SsrfBlockedError("blocked host"), 400),
    (UnsupportedFileError("nope"), 415),
    (FileTooLargeError("too big"), 413),
    (JdFetchError("dns fail"), 502),
])
def test_fetch_errors_map_to_http_codes(recruiter_client, exc, code):
    with patch("app.api.v2.routers.intake_jd.extract_jd", AsyncMock(side_effect=exc)):
        resp = recruiter_client.post(ENDPOINT, data={"text": "http://example.com/jd"})
    assert resp.status_code == code
