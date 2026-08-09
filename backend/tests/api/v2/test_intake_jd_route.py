"""Tests for POST /api/v2/intake/jd/extract.

The router validates "at least one of text/file", reads settings.INTAKE_JD_MODEL,
calls extract_jd, and maps the jd_fetch exception hierarchy onto HTTP codes.
extract_jd is patched, so no gateway call is made; the router's only LLM
responsibility is handing the dependency and the alias to it.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.intake.jd_fetch import (
    FileTooLargeError,
    JdFetchError,
    SsrfBlockedError,
    UnsupportedFileError,
)

ENDPOINT = "/api/v2/intake/jd/extract"


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

    async def fake_extract(llm, model, text, file):
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


def test_router_passes_the_configured_alias(recruiter_client):
    captured = {}

    async def fake_extract(llm, model, text, file):
        captured["model"] = model
        return _ok_result()

    with patch("app.api.v2.routers.intake_jd.extract_jd", fake_extract):
        resp = recruiter_client.post(ENDPOINT, data={"text": "Senior Engineer in NYC"})

    assert resp.status_code == 200
    assert captured["model"] == "intake-jd"


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
