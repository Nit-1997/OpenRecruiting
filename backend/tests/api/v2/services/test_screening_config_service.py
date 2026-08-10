"""Tests for the screening question generator + config service.

The LLM is mocked via the single `_call_llm` seam on the generator, and the
Supabase client is a hand-rolled fake that records the RPC/update calls — no
network, no DB. Mirrors the seam-mock style in
tests/services/intake/test_parse_intent_service.py.
"""

import pytest

from app.api.v2.schemas.screening import ScreeningConfig, ScreeningQuestion
from app.api.v2.services.screening_config_service import ScreeningConfigService
from app.api.v2.services.screening_question_generator import (
    ScreeningQuestionGenerator,
)


# --------------------------------------------------------------------------- #
# Fake Supabase client                                                        #
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeUpdateChain:
    """Records .update(...).eq(...).execute_async() and returns canned data."""

    def __init__(self, recorder, table_name, return_data):
        self._recorder = recorder
        self._table_name = table_name
        self._return_data = return_data
        self._patch = None
        self._filters = []

    def update(self, patch):
        self._patch = patch
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def select(self, *_args, **_kwargs):
        return self

    def single(self):
        return self

    async def execute_async(self):
        self._recorder.update_calls.append(
            {
                "table": self._table_name,
                "patch": self._patch,
                "filters": list(self._filters),
            }
        )
        return _FakeResponse(self._return_data)


class _FakeSupabase:
    def __init__(self, *, rpc_return=None, update_return=None, table_return=None):
        self.rpc_calls = []
        self.update_calls = []
        self._rpc_return = rpc_return if rpc_return is not None else {"config_id": "cfg-1"}
        self._update_return = update_return
        self._table_return = table_return

    async def rpc(self, function_name, params):
        self.rpc_calls.append({"name": function_name, "params": params})
        return _FakeResponse(self._rpc_return)

    def table(self, table_name):
        data = self._update_return if self._update_return is not None else self._table_return
        return _FakeUpdateChain(self, table_name, data)


# --------------------------------------------------------------------------- #
# Generator                                                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generate_returns_rich_questions(monkeypatch):
    canned = {
        "questions": [
            {
                "title": "Toughest production incident",
                "prompt": "Walk me through the hardest production incident you owned end to end.",
                "probe": "What was the root cause and how did you prevent a repeat?",
                "signal": "EXECUTION",
                "dimension": "ownership",
                "duration_minutes": 6,
            },
            {
                "title": "Scaling a service",
                "prompt": "Tell me about a time you scaled a service under load.",
                "probe": "What broke first and why?",
                "signal": "DEPTH",
                "dimension": "systems",
                "duration_minutes": 5,
            },
        ]
    }

    async def _fake_call_llm(self, prompt):
        return canned

    monkeypatch.setattr(ScreeningQuestionGenerator, "_call_llm", _fake_call_llm)

    gen = ScreeningQuestionGenerator()
    questions = await gen.generate(
        role_context="Senior Backend Engineer",
        must_haves=["Python", "distributed systems"],
        cortex_gaps=["unclear on on-call ownership"],
        preferences="lean harder on incident response",
    )

    assert len(questions) == 2
    assert all(isinstance(q, ScreeningQuestion) for q in questions)
    first = questions[0]
    assert first.signal == "EXECUTION"
    assert first.dimension == "ownership"
    assert first.duration_minutes == 6
    assert "hardest production incident" in first.prompt
    # order_index is assigned positionally by the generator.
    assert [q.order_index for q in questions] == [0, 1]


@pytest.mark.asyncio
async def test_generate_tolerates_missing_optional_fields(monkeypatch):
    async def _fake_call_llm(self, prompt):
        return {"questions": [{"title": "Just title", "prompt": "Just a prompt"}]}

    monkeypatch.setattr(ScreeningQuestionGenerator, "_call_llm", _fake_call_llm)

    questions = await ScreeningQuestionGenerator().generate(
        role_context="PM",
        must_haves=[],
        cortex_gaps=[],
        preferences=None,
    )
    assert len(questions) == 1
    q = questions[0]
    assert q.title == "Just title"
    assert q.probe is None
    assert q.signal is None
    assert q.duration_minutes == 5  # schema default


# --------------------------------------------------------------------------- #
# Config service — upsert via RPC                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_upsert_calls_rpc():
    supabase = _FakeSupabase(rpc_return={"config_id": "cfg-123"})
    service = ScreeningConfigService(supabase)

    cfg = ScreeningConfig(
        round_id="round-abc",
        enabled=True,
        voice="aura-luna-en",
        validity_days=14,
        deploy_scope="all_resume_passed",
        questions=[
            ScreeningQuestion(
                order_index=0,
                title="Q1",
                prompt="Prompt 1",
                probe="Probe 1",
                signal="EXECUTION",
                dimension="ownership",
                duration_minutes=5,
            )
        ],
    )

    result = await service.upsert(cfg, requisition_id="req-xyz", created_by="user-1")

    assert result == {"config_id": "cfg-123"}
    assert len(supabase.rpc_calls) == 1
    call = supabase.rpc_calls[0]
    assert call["name"] == "screening_save_config"
    payload = call["params"]["p"]
    assert payload["round_id"] == "round-abc"
    assert payload["requisition_id"] == "req-xyz"
    assert payload["created_by"] == "user-1"
    assert payload["enabled"] is True
    assert payload["validity_days"] == 14
    assert payload["deploy_scope"] == "all_resume_passed"
    assert isinstance(payload["questions"], list)
    assert payload["questions"][0]["title"] == "Q1"
    assert payload["questions"][0]["signal"] == "EXECUTION"
    assert payload["questions"][0]["order_index"] == 0


@pytest.mark.asyncio
async def test_set_enabled_updates_flag():
    supabase = _FakeSupabase()
    service = ScreeningConfigService(supabase)

    await service.set_enabled("round-abc", True)

    assert len(supabase.update_calls) == 1
    call = supabase.update_calls[0]
    assert call["table"] == "round_screening_configs"
    assert call["patch"]["enabled"] is True
    assert ("round_id", "round-abc") in call["filters"]


@pytest.mark.asyncio
async def test_set_persona_writes_snapshot():
    supabase = _FakeSupabase()
    service = ScreeningConfigService(supabase)

    snapshot = {"dimensions": [{"key": "tone_rapport", "value": "Warm."}], "text": "..."}
    result = await service.set_persona("round-abc", "persona-1", snapshot)

    assert result == {"round_id": "round-abc", "persona_id": "persona-1"}
    assert len(supabase.update_calls) == 1
    call = supabase.update_calls[0]
    assert call["table"] == "round_screening_configs"
    # Both persona_id and persona_snapshot are written so the voice agent reads them.
    assert call["patch"]["persona_id"] == "persona-1"
    assert call["patch"]["persona_snapshot"] == snapshot
    assert ("round_id", "round-abc") in call["filters"]


# --------------------------------------------------------------------------- #
# _call_llm — the single LLM seam. Every test above mocks it; these test its body.
# --------------------------------------------------------------------------- #
import structlog  # noqa: E402
from llm_core.errors import LLMError  # noqa: E402

import app.api.v2.services.screening_question_generator as generator_module  # noqa: E402

FORCED = {"type": "function", "function": {"name": "emit_screening_questions"}}


@pytest.mark.asyncio
async def test_call_llm_returns_the_tool_arguments(fake_llm, monkeypatch):
    monkeypatch.setattr(generator_module, "get_llm_client", lambda: fake_llm)
    payload = {"questions": [{"title": "Incident", "prompt": "Tell me about one."}]}
    fake_llm.queue_tool_call("emit_screening_questions", payload)

    out = await ScreeningQuestionGenerator()._call_llm("some prompt")

    assert out == payload


@pytest.mark.asyncio
async def test_call_llm_returns_empty_questions_without_a_tool_call(fake_llm, monkeypatch):
    """Defence in depth behind the forced tool: generate() must get an empty
    list rather than an exception, and the event must be visible."""
    monkeypatch.setattr(generator_module, "get_llm_client", lambda: fake_llm)
    fake_llm.queue_text("Here are some ideas...")

    with structlog.testing.capture_logs() as logs:
        out = await ScreeningQuestionGenerator()._call_llm("some prompt")

    assert out == {"questions": []}
    assert [e["event"] for e in logs] == ["screening_questions_no_tool_call"]


@pytest.mark.asyncio
async def test_call_llm_returns_empty_questions_on_a_truncated_call(fake_llm, monkeypatch):
    """A call that exists and is named correctly but whose argument JSON was cut
    off arrives as arguments={}. tool_call_named cannot see it, so the `or`
    fallback is what keeps generate() from a KeyError on "questions"."""
    monkeypatch.setattr(generator_module, "get_llm_client", lambda: fake_llm)
    fake_llm.queue_tool_call("emit_screening_questions", {})

    out = await ScreeningQuestionGenerator()._call_llm("some prompt")

    assert out == {"questions": []}


@pytest.mark.asyncio
async def test_generate_returns_empty_list_on_gateway_error(fake_llm, monkeypatch):
    monkeypatch.setattr(generator_module, "get_llm_client", lambda: fake_llm)
    fake_llm.queue_error(LLMError("gateway 429", alias="screening-generator", status=429))

    questions = await ScreeningQuestionGenerator().generate(
        role_context="PM", must_haves=[], cortex_gaps=[], preferences=None
    )

    assert questions == []


@pytest.mark.asyncio
async def test_call_llm_sends_the_alias_and_a_forced_openai_tool(fake_llm, monkeypatch):
    monkeypatch.setattr(generator_module, "get_llm_client", lambda: fake_llm)
    fake_llm.queue_tool_call("emit_screening_questions", {"questions": []})

    await ScreeningQuestionGenerator()._call_llm("some prompt")

    call = fake_llm.calls[0]
    assert call["model"] == "screening-generator"   # was "claude-sonnet-4-6"
    assert call["max_tokens"] == 2000
    assert call["tool_choice"] == FORCED
    assert call["tools"][0]["type"] == "function"
    assert call["tools"][0]["function"]["name"] == "emit_screening_questions"
    assert call["messages"] == [{"role": "user", "content": "some prompt"}]
