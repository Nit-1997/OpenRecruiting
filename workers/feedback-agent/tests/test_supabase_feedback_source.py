from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import importlib.util
import sys

import pytest


class _StubLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None


src_module = ModuleType("src")
config_module = ModuleType("src.config")
config_module.get_settings = lambda: SimpleNamespace(
    supabase_url="https://example.supabase.co",
    supabase_secret_key="secret",
)
logging_module = ModuleType("src.logging")
logging_module.get_logger = lambda _name: _StubLogger()

sys.modules["src"] = src_module
sys.modules["src.config"] = config_module
sys.modules["src.logging"] = logging_module

module_path = Path(__file__).resolve().parents[1] / "src" / "clients" / "supabase.py"
spec = importlib.util.spec_from_file_location("supabase_under_test", module_path)
supabase_under_test = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(supabase_under_test)

SupabaseClient = supabase_under_test.SupabaseClient


class _Response:
    def __init__(self, data, status_code: int = 200):
        self._data = data
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._data


def _build_client(monkeypatch, resolver):
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_secret_key="secret",
    )
    monkeypatch.setattr(supabase_under_test, "get_settings", lambda: settings)

    http_client = MagicMock()

    async def _fake_get(url, params=None, headers=None, timeout=None):
        return resolver(url, params or {})

    http_client.get = AsyncMock(side_effect=_fake_get)
    monkeypatch.setattr(supabase_under_test, "get_async_http_client", lambda: http_client)
    return SupabaseClient()


@pytest.mark.asyncio
async def test_get_feedback_source_completed_uses_bot(monkeypatch):
    def resolver(url, params):
        if url.endswith("/rest/v1/transcripts"):
            return _Response([{
                "segments": [{"words": [{"text": "hello"}]}],
                "feedback_transcript": "OpenRecruiting: prompt\n\nInterviewer: " + ("a" * 150),
            }])
        if url.endswith("/rest/v1/candidate_rounds"):
            return _Response([{"scorecard_transcript": None, "candidates": {"name": "Test Candidate"}}])
        if url.endswith("/rest/v1/recall_bots"):
            return _Response([{
                "feedback_status": "completed",
                "feedback_started_at": "2026-04-08T09:51:00Z",
                "joined_at": "2026-04-08T08:40:00Z",
            }])
        return _Response([])

    client = _build_client(monkeypatch, resolver)
    result = await client.get_feedback_source("cr-1")
    assert result["source"] == "bot"


@pytest.mark.asyncio
async def test_get_feedback_source_completed_without_content_is_none(monkeypatch):
    def resolver(url, params):
        if url.endswith("/rest/v1/transcripts"):
            return _Response([{"segments": [], "feedback_transcript": None}])
        if url.endswith("/rest/v1/candidate_rounds"):
            return _Response([{"scorecard_transcript": None, "candidates": {"name": "Test Candidate"}}])
        if url.endswith("/rest/v1/recall_bots"):
            return _Response([{
                "feedback_status": "completed",
                "feedback_started_at": "2026-04-08T09:51:00Z",
                "joined_at": "2026-04-08T08:40:00Z",
            }])
        return _Response([])

    client = _build_client(monkeypatch, resolver)
    result = await client.get_feedback_source("cr-5")
    assert result["source"] == "none"


@pytest.mark.asyncio
async def test_get_feedback_source_partial_with_meaningful_content_uses_bot(monkeypatch):
    def resolver(url, params):
        if url.endswith("/rest/v1/transcripts"):
            return _Response([{
                "segments": [],
                "feedback_transcript": "OpenRecruiting: prompt\n\nInterviewer: " + ("a" * 150),
            }])
        if url.endswith("/rest/v1/candidate_rounds"):
            return _Response([{"scorecard_transcript": None, "candidates": {"name": "Test Candidate"}}])
        if url.endswith("/rest/v1/recall_bots"):
            return _Response([{
                "feedback_status": "partial",
                "feedback_started_at": "2026-04-08T09:51:00Z",
                "joined_at": "2026-04-08T08:40:00Z",
            }])
        return _Response([])

    client = _build_client(monkeypatch, resolver)
    result = await client.get_feedback_source("cr-2")
    assert result["source"] == "bot"


@pytest.mark.asyncio
async def test_get_feedback_source_partial_without_meaningful_content_is_none(monkeypatch):
    def resolver(url, params):
        if url.endswith("/rest/v1/transcripts"):
            return _Response([{
                "segments": [],
                "feedback_transcript": "OpenRecruiting: prompt\n\nOpenRecruiting: follow-up",
            }])
        if url.endswith("/rest/v1/candidate_rounds"):
            return _Response([{"scorecard_transcript": None, "candidates": {"name": "Test Candidate"}}])
        if url.endswith("/rest/v1/recall_bots"):
            return _Response([{
                "feedback_status": "partial",
                "feedback_started_at": "2026-04-08T09:51:00Z",
                "joined_at": "2026-04-08T08:40:00Z",
            }])
        return _Response([])

    client = _build_client(monkeypatch, resolver)
    result = await client.get_feedback_source("cr-3")
    assert result["source"] == "none"


@pytest.mark.asyncio
async def test_get_feedback_source_collecting_is_none(monkeypatch):
    def resolver(url, params):
        if url.endswith("/rest/v1/transcripts"):
            return _Response([{"segments": [{"words": [{"text": "hello"}]}], "feedback_transcript": None}])
        if url.endswith("/rest/v1/candidate_rounds"):
            return _Response([{"scorecard_transcript": None, "candidates": {"name": "Test Candidate"}}])
        if url.endswith("/rest/v1/recall_bots"):
            return _Response([{
                "feedback_status": "collecting",
                "feedback_started_at": "2026-04-08T09:51:00Z",
                "joined_at": "2026-04-08T08:40:00Z",
            }])
        return _Response([])

    client = _build_client(monkeypatch, resolver)
    result = await client.get_feedback_source("cr-4")
    assert result["source"] == "none"


@pytest.mark.asyncio
async def test_get_feedback_source_completed_with_simple_segments_uses_bot(monkeypatch):
    def resolver(url, params):
        if url.endswith("/rest/v1/transcripts"):
            return _Response([{
                "segments": [
                    {"speaker": "Interviewer", "text": "a" * 170, "start_timestamp": 5000},
                ],
                "feedback_transcript": None,
            }])
        if url.endswith("/rest/v1/candidate_rounds"):
            return _Response([{"scorecard_transcript": None, "candidates": {"name": "Test Candidate"}}])
        if url.endswith("/rest/v1/recall_bots"):
            return _Response([{
                "feedback_status": "completed",
                "feedback_started_at": "2026-04-08T09:51:00Z",
                "joined_at": "2026-04-08T08:40:00Z",
            }])
        return _Response([])

    client = _build_client(monkeypatch, resolver)
    result = await client.get_feedback_source("cr-6")
    assert result["source"] == "bot"
