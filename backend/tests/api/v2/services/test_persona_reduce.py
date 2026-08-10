"""Tests for the Cortex persona reader + config-time REDUCE service.

Two mockable seams keep these tests network-free:
  - CortexPersonaReader.read_interviewer_signal  (the whole Cortex read)
  - PersonaReduceService._synthesize_dimensions  (the single LLM call)
  - CortexPersonaReader._execute_query           (the single MCP HTTP call)

The Supabase client is a hand-rolled fake that records the personas insert.
Mirrors the seam-mock style in test_screening_config_service.py.
"""

import pytest

from intake_core.screening.persona import (
    PersonaDimension,
    SCREENING_GUARDRAILS,
)

from app.api.v2.services.cortex_persona_reader import CortexPersonaReader
from app.api.v2.services.persona_reduce_service import (
    GENERIC_DIMENSION_VALUES,
    PersonaReduceService,
)


# --------------------------------------------------------------------------- #
# Fake Supabase client                                                        #
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeInsertChain:
    def __init__(self, recorder, table_name, return_data):
        self._recorder = recorder
        self._table_name = table_name
        self._return_data = return_data
        self._payload = None

    def insert(self, payload):
        self._payload = payload
        return self

    async def execute_async(self):
        self._recorder.insert_calls.append(
            {"table": self._table_name, "payload": self._payload}
        )
        return _FakeResponse(self._return_data)


class _FakeSupabase:
    def __init__(self, *, insert_return=None):
        self.insert_calls = []
        self._insert_return = (
            insert_return if insert_return is not None else {"id": "persona-1"}
        )

    def table(self, table_name):
        return _FakeInsertChain(self, table_name, self._insert_return)


# --------------------------------------------------------------------------- #
# Reduce service                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_derive_uses_cortex_signal(monkeypatch):
    canned_signal = [
        {
            "trait": "Structured probing",
            "category": "process",
            "evidence": "Always asks for a concrete example then drills into trade-offs.",
            "frequency": 7,
        },
        {
            "trait": "Warm rapport",
            "category": "style",
            "evidence": "Opens with light small talk before the first question.",
            "frequency": 5,
        },
    ]

    high_conf_dims = [
        PersonaDimension(
            key="tone_rapport",
            value="Warm and conversational; opens with light small talk.",
            confidence=0.9,
            source="cortex",
        ),
        PersonaDimension(
            key="probing_depth",
            value="Asks for a concrete example then drills into trade-offs.",
            confidence=0.8,
            source="cortex",
        ),
        PersonaDimension(
            key="eval_priorities",
            value="Weighs execution and ownership over pedigree.",
            confidence=0.85,
            source="cortex",
        ),
        PersonaDimension(
            key="must_haves",
            value="Hands-on distributed-systems experience.",
            confidence=0.7,
            source="cortex",
        ),
        PersonaDimension(
            key="structure",
            value="Three blocks across ~20 minutes, time-boxed.",
            confidence=0.75,
            source="cortex",
        ),
    ]

    async def _fake_read(self, *, org_id, org_name, role_title):
        assert role_title == "Senior Backend Engineer"
        return canned_signal

    async def _fake_synth(self, signal):
        assert signal == canned_signal
        return high_conf_dims

    monkeypatch.setattr(
        CortexPersonaReader, "read_interviewer_signal", _fake_read
    )
    monkeypatch.setattr(
        PersonaReduceService, "_synthesize_dimensions", _fake_synth
    )

    supabase = _FakeSupabase(insert_return={"id": "persona-99"})
    service = PersonaReduceService(supabase)

    result = await service.derive(
        requisition_id="req-1",
        org_id="org-1",
        org_name="Acme",
        role_title="Senior Backend Engineer",
        created_by="user-1",
    )

    # All high-confidence dims keep cortex source.
    dims_by_key = {d["key"]: d for d in result["dimensions"]}
    assert dims_by_key["tone_rapport"]["source"] == "cortex"
    assert dims_by_key["probing_depth"]["source"] == "cortex"
    assert dims_by_key["eval_priorities"]["source"] == "cortex"

    # Composed text contains a high-confidence value AND the guardrails.
    assert "drills into trade-offs" in result["composed_text"]
    assert SCREENING_GUARDRAILS.strip() in result["composed_text"]

    # A personas row was persisted with the composed text + JSONB dimensions.
    assert len(supabase.insert_calls) == 1
    call = supabase.insert_calls[0]
    assert call["table"] == "personas"
    payload = call["payload"]
    assert payload["organization_id"] == "org-1"
    assert payload["requisition_id"] == "req-1"
    assert payload["created_by"] == "user-1"
    assert payload["composed_text"] == result["composed_text"]
    assert isinstance(payload["dimensions"], list)
    assert payload["dimensions"][0]["key"] in [d.key for d in high_conf_dims]

    assert result["persona_id"] == "persona-99"
    # snapshot shape for the downstream config consumer
    assert result["persona_snapshot"]["text"] == result["composed_text"]
    assert isinstance(result["persona_snapshot"]["dimensions"], list)


@pytest.mark.asyncio
async def test_low_confidence_falls_back_to_generic(monkeypatch):
    async def _fake_read(self, *, org_id, org_name, role_title):
        return [{"trait": "x", "category": "y", "evidence": "z", "frequency": 1}]

    async def _fake_synth(self, signal):
        return [
            PersonaDimension(
                key="tone_rapport",
                value="Confident strong value.",
                confidence=0.9,
                source="cortex",
            ),
            PersonaDimension(
                key="probing_depth",
                value="Weak low-confidence guess.",
                confidence=0.2,  # below threshold
                source="cortex",
            ),
        ]

    monkeypatch.setattr(
        CortexPersonaReader, "read_interviewer_signal", _fake_read
    )
    monkeypatch.setattr(
        PersonaReduceService, "_synthesize_dimensions", _fake_synth
    )

    service = PersonaReduceService(_FakeSupabase())
    result = await service.derive(
        requisition_id="req-1",
        org_id="org-1",
        org_name="Acme",
        role_title="PM",
        created_by=None,
    )

    dims_by_key = {d["key"]: d for d in result["dimensions"]}
    assert dims_by_key["tone_rapport"]["source"] == "cortex"
    # below-threshold dim flips to generic
    assert dims_by_key["probing_depth"]["source"] == "generic"
    assert (
        dims_by_key["probing_depth"]["value"]
        == GENERIC_DIMENSION_VALUES["probing_depth"]
    )
    # the weak cortex text must NOT have leaked into the composed persona
    assert "Weak low-confidence guess" not in result["composed_text"]


@pytest.mark.asyncio
async def test_cold_start_all_generic(monkeypatch):
    async def _fake_read(self, *, org_id, org_name, role_title):
        return []  # no Cortex signal

    # _synthesize_dimensions must not even be called on cold start, but if it is,
    # make it explode so the test catches a regression.
    async def _explode(self, signal):
        raise AssertionError("synth should be skipped on empty signal")

    monkeypatch.setattr(
        CortexPersonaReader, "read_interviewer_signal", _fake_read
    )
    monkeypatch.setattr(
        PersonaReduceService, "_synthesize_dimensions", _explode
    )

    service = PersonaReduceService(_FakeSupabase())
    result = await service.derive(
        requisition_id="req-1",
        org_id="org-1",
        org_name="Acme",
        role_title="Anything",
        created_by=None,
    )

    # All five Cortex-fillable dims are present and generic.
    assert len(result["dimensions"]) == len(GENERIC_DIMENSION_VALUES)
    assert all(d["source"] == "generic" for d in result["dimensions"])
    # Guardrails are always present; never raises.
    assert SCREENING_GUARDRAILS.strip() in result["composed_text"]


# --------------------------------------------------------------------------- #
# Reader — defensive parsing                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reader_empty_on_mcp_error(monkeypatch):
    reader = CortexPersonaReader()

    async def _raise(self, token, query, params):
        raise RuntimeError("boom")

    monkeypatch.setattr(CortexPersonaReader, "_execute_query", _raise)
    monkeypatch.setattr(
        "app.api.v2.services.cortex_persona_reader.mint_cortex_service_token",
        lambda *, org_id, org_name: ("tok", 300),
    )

    rows = await reader.read_interviewer_signal(
        org_id="org-1", org_name="Acme", role_title="Eng"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_reader_empty_on_rejected_status(monkeypatch):
    reader = CortexPersonaReader()

    async def _rejected(self, token, query, params):
        return {
            "result": {
                "content": [
                    {"text": '{"status": "rejected", "error": "no subqueries"}'}
                ]
            }
        }

    monkeypatch.setattr(CortexPersonaReader, "_execute_query", _rejected)
    monkeypatch.setattr(
        "app.api.v2.services.cortex_persona_reader.mint_cortex_service_token",
        lambda *, org_id, org_name: ("tok", 300),
    )

    rows = await reader.read_interviewer_signal(
        org_id="org-1", org_name="Acme", role_title="Eng"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_reader_parses_rows(monkeypatch):
    reader = CortexPersonaReader()

    async def _ok(self, token, query, params):
        assert params["title"] == "Eng"
        return {
            "result": {
                "content": [
                    {
                        "text": (
                            '{"status": "ok", "data": ['
                            '{"trait": "Structured probing", "category": "process",'
                            ' "evidence": "drills in", "frequency": 4}]}'
                        )
                    }
                ]
            }
        }

    monkeypatch.setattr(CortexPersonaReader, "_execute_query", _ok)
    monkeypatch.setattr(
        "app.api.v2.services.cortex_persona_reader.mint_cortex_service_token",
        lambda *, org_id, org_name: ("tok", 300),
    )

    rows = await reader.read_interviewer_signal(
        org_id="org-1", org_name="Acme", role_title="Eng"
    )
    assert len(rows) == 1
    assert rows[0]["trait"] == "Structured probing"
    assert rows[0]["frequency"] == 4


# --------------------------------------------------------------------------- #
# _synthesize_dimensions — the single LLM seam, tested directly against FakeLLM.
# Every test above mocks this method out; these are the only tests of its body.
# --------------------------------------------------------------------------- #
import app.api.v2.services.persona_reduce_service as persona_module  # noqa: E402

_SIGNAL = [{"trait": "asks for trade-offs", "category": "probing", "frequency": 4}]

FORCED = {"type": "function", "function": {"name": "emit_persona_dimensions"}}


def _service(fake_llm, monkeypatch):
    """Build the service without touching Supabase or Cortex.

    _synthesize_dimensions reads neither self.supabase nor self.reader, but
    __init__ constructs a CortexPersonaReader, so the seam is patched at the
    module attribute the method actually calls.
    """
    monkeypatch.setattr(persona_module, "get_llm_client", lambda: fake_llm)
    return PersonaReduceService(supabase=object())


@pytest.mark.asyncio
async def test_synthesize_maps_tool_output_to_cortex_dimensions(fake_llm, monkeypatch):
    service = _service(fake_llm, monkeypatch)
    fake_llm.queue_tool_call(
        "emit_persona_dimensions",
        {
            "dimensions": [
                {"key": "probing_depth", "value": "Push on trade-offs.", "confidence": 0.9},
                {"key": "not_a_dimension", "value": "ignored", "confidence": 1.0},
            ]
        },
    )

    dims = await service._synthesize_dimensions(_SIGNAL)

    assert [d.key for d in dims] == ["probing_depth"]
    assert dims[0].source == "cortex"
    assert dims[0].confidence == 0.9


@pytest.mark.asyncio
async def test_synthesize_clamps_confidence_and_survives_bad_rows(fake_llm, monkeypatch):
    service = _service(fake_llm, monkeypatch)
    fake_llm.queue_tool_call(
        "emit_persona_dimensions",
        {
            "dimensions": [
                {"key": "tone_rapport", "value": "Warm.", "confidence": 7.5},
                "not-a-dict",
                {"key": "structure", "value": "Ordered.", "confidence": "nonsense"},
            ]
        },
    )

    dims = await service._synthesize_dimensions(_SIGNAL)

    by_key = {d.key: d for d in dims}
    assert by_key["tone_rapport"].confidence == 1.0
    assert by_key["structure"].confidence == 0.0


@pytest.mark.asyncio
async def test_synthesize_sends_its_own_alias_and_a_forced_openai_tool(fake_llm, monkeypatch):
    """persona-reduce, NOT screening-generator. This service borrowed the
    generator's setting before the migration; the two are now independent, which
    is what lets Task 7 flip SCREENING_GENERATOR_MODEL safely."""
    service = _service(fake_llm, monkeypatch)
    fake_llm.queue_tool_call("emit_persona_dimensions", {"dimensions": []})

    await service._synthesize_dimensions(_SIGNAL)

    call = fake_llm.calls[0]
    assert call["model"] == "persona-reduce"
    assert call["max_tokens"] == 2000
    assert call["tool_choice"] == FORCED
    assert call["tools"][0]["type"] == "function"
    assert call["tools"][0]["function"]["name"] == "emit_persona_dimensions"
    assert "asks for trade-offs" in call["messages"][0]["content"]


@pytest.mark.asyncio
async def test_synthesize_yields_nothing_on_a_prose_reply(fake_llm, monkeypatch):
    """Defence in depth behind the forced tool. No dimensions means derive()
    composes an all-generic persona rather than failing."""
    service = _service(fake_llm, monkeypatch)
    fake_llm.queue_text("Here is my analysis of the interviewer style.")

    assert await service._synthesize_dimensions(_SIGNAL) == []


@pytest.mark.asyncio
async def test_synthesize_does_not_swallow_gateway_errors(fake_llm, monkeypatch):
    """derive() owns the fallback (persona_reduce_service.derive), not this
    method — so the error has to reach it."""
    from llm_core.errors import LLMError

    service = _service(fake_llm, monkeypatch)
    fake_llm.queue_error(LLMError("gateway 500", alias="persona-reduce", status=500))

    with pytest.raises(LLMError):
        await service._synthesize_dimensions(_SIGNAL)
