"""Dedicated unit tests for the two Cortex readers.

The readers are otherwise only exercised through seam mocks in the layer above
(persona reduce + screening suggestion), so their OWN logic — envelope/SSE
parsing, the cold-start/error -> [] contract, and the persona reader's
role-scoped -> org-wide fallback — is what this file pins.

Two seams are mocked at the LOWEST levels:
  - `_execute_query` (the per-class MCP call) for the parse / fallback / error
    contracts, AND
  - the raw httpx `/mcp` POST via respx so the REAL `_execute_query` +
    `_parse_sse_jsonrpc` + `_parse_rows` run end to end (JSON and SSE transports).

`mint_cortex_service_token` is patched per-module so no real signing key is
needed; one test lets it raise to cover the token-mint-failure -> [] path.
"""

import httpx
import pytest

from app.api.v2.services import cortex_persona_reader as persona_mod
from app.api.v2.services.cortex_gap_reader import CortexGapReader
from app.api.v2.services.cortex_persona_reader import CortexPersonaReader

PERSONA_MINT = (
    "app.api.v2.services.cortex_persona_reader.mint_cortex_service_token"
)
GAP_MINT = "app.api.v2.services.cortex_gap_reader.mint_cortex_service_token"


def _patch_mint(monkeypatch, target):
    monkeypatch.setattr(
        target, lambda *, org_id, org_name: ("tok", 300)
    )


def _envelope(text: str) -> dict:
    """A well-formed MCP JSON-RPC result wrapping `text` as the tool output."""
    return {"result": {"content": [{"text": text}]}}


# --------------------------------------------------------------------------- #
# CortexPersonaReader.read_interviewer_signal                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_persona_parses_well_formed_rows(monkeypatch):
    reader = CortexPersonaReader()
    _patch_mint(monkeypatch, PERSONA_MINT)

    async def _ok(self, token, query, params):
        assert params["title"] == "Eng"
        return _envelope(
            '{"status": "ok", "data": ['
            '{"trait": "Structured probing", "category": "process",'
            ' "evidence": "drills into trade-offs", "frequency": 4}]}'
        )

    monkeypatch.setattr(CortexPersonaReader, "_execute_query", _ok)

    rows = await reader.read_interviewer_signal(
        org_id="org-1", org_name="Acme", role_title="Eng"
    )
    assert rows == [
        {
            "trait": "Structured probing",
            "category": "process",
            "evidence": "drills into trade-offs",
            "frequency": 4,
        }
    ]


@pytest.mark.asyncio
async def test_persona_rejected_status_returns_empty(monkeypatch):
    reader = CortexPersonaReader()
    _patch_mint(monkeypatch, PERSONA_MINT)

    async def _rejected(self, token, query, params):
        return _envelope('{"status": "rejected", "error": "no subqueries"}')

    monkeypatch.setattr(CortexPersonaReader, "_execute_query", _rejected)

    rows = await reader.read_interviewer_signal(
        org_id="org-1", org_name="Acme", role_title="Eng"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_persona_malformed_envelope_returns_empty(monkeypatch):
    reader = CortexPersonaReader()
    _patch_mint(monkeypatch, PERSONA_MINT)

    # Both queries (role-scoped then org-wide fallback) get a junk envelope with
    # no parseable content -> _parse_rows swallows the KeyError -> [].
    async def _junk(self, token, query, params):
        return {"not": "an mcp envelope"}

    monkeypatch.setattr(CortexPersonaReader, "_execute_query", _junk)

    rows = await reader.read_interviewer_signal(
        org_id="org-1", org_name="Acme", role_title="Eng"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_persona_token_mint_failure_returns_empty(monkeypatch):
    reader = CortexPersonaReader()

    def _boom(*, org_id, org_name):
        raise RuntimeError("no signing key configured")

    monkeypatch.setattr(PERSONA_MINT, _boom)

    # _execute_query must never be reached when the token can't be minted.
    async def _should_not_run(self, token, query, params):
        raise AssertionError("query attempted despite token-mint failure")

    monkeypatch.setattr(CortexPersonaReader, "_execute_query", _should_not_run)

    rows = await reader.read_interviewer_signal(
        org_id="org-1", org_name="Acme", role_title="Eng"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_persona_transport_error_returns_empty(monkeypatch):
    reader = CortexPersonaReader()
    _patch_mint(monkeypatch, PERSONA_MINT)

    async def _raise(self, token, query, params):
        raise httpx.ConnectError("cortex unreachable")

    monkeypatch.setattr(CortexPersonaReader, "_execute_query", _raise)

    rows = await reader.read_interviewer_signal(
        org_id="org-1", org_name="Acme", role_title="Eng"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_persona_empty_role_scope_falls_back_to_org_wide(monkeypatch):
    """Role-scoped query returning nothing must trigger the org-wide fallback —
    the second _execute_query call uses the org cypher with NO $title param."""
    reader = CortexPersonaReader()
    _patch_mint(monkeypatch, PERSONA_MINT)

    calls = []

    async def _two_phase(self, token, query, params):
        calls.append({"query": query, "params": params})
        if len(calls) == 1:
            # role-scoped: well-formed but empty -> triggers fallback
            return _envelope('{"status": "ok", "data": []}')
        # org-wide fallback: returns a trait
        return _envelope(
            '{"status": "ok", "data": ['
            '{"trait": "Warm rapport", "category": "style",'
            ' "evidence": "opens with small talk", "frequency": 9}]}'
        )

    monkeypatch.setattr(CortexPersonaReader, "_execute_query", _two_phase)

    rows = await reader.read_interviewer_signal(
        org_id="org-1", org_name="Acme", role_title="Brand New Role"
    )

    # Exactly two calls: role-scoped, then org-wide fallback.
    assert len(calls) == 2
    assert calls[0]["query"] == persona_mod._SIGNAL_CYPHER
    assert calls[0]["params"] == {"title": "Brand New Role"}
    assert calls[1]["query"] == persona_mod._SIGNAL_CYPHER_ORG
    assert calls[1]["params"] == {}

    # The org-wide rows are what the caller gets back.
    assert rows == [
        {
            "trait": "Warm rapport",
            "category": "style",
            "evidence": "opens with small talk",
            "frequency": 9,
        }
    ]


@pytest.mark.asyncio
async def test_persona_role_scope_hit_skips_fallback(monkeypatch):
    """A non-empty role-scoped result must NOT trigger the org-wide fallback."""
    reader = CortexPersonaReader()
    _patch_mint(monkeypatch, PERSONA_MINT)

    calls = []

    async def _once(self, token, query, params):
        calls.append(query)
        return _envelope(
            '{"status": "ok", "data": ['
            '{"trait": "Structured probing", "category": "process",'
            ' "evidence": "drills in", "frequency": 4}]}'
        )

    monkeypatch.setattr(CortexPersonaReader, "_execute_query", _once)

    rows = await reader.read_interviewer_signal(
        org_id="org-1", org_name="Acme", role_title="Eng"
    )

    assert len(calls) == 1
    assert calls[0] == persona_mod._SIGNAL_CYPHER
    assert rows[0]["trait"] == "Structured probing"


# --------------------------------------------------------------------------- #
# CortexGapReader.read_recurring_gaps                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_gap_parses_well_formed_rows(monkeypatch):
    reader = CortexGapReader()
    _patch_mint(monkeypatch, GAP_MINT)

    async def _ok(self, token, query, params):
        assert params["req_ref"] == "req-1"
        return _envelope(
            '{"status": "ok", "data": ['
            '{"competency": "System Design", "weak_candidates": 3},'
            '{"competency": "Communication", "weak_candidates": 2}]}'
        )

    monkeypatch.setattr(CortexGapReader, "_execute_query", _ok)

    rows = await reader.read_recurring_gaps(
        org_id="org-1", org_name="Acme", requisition_id="req-1"
    )
    assert rows == [
        {"competency": "System Design", "weak_candidates": 3},
        {"competency": "Communication", "weak_candidates": 2},
    ]


@pytest.mark.asyncio
async def test_gap_rejected_status_returns_empty(monkeypatch):
    reader = CortexGapReader()
    _patch_mint(monkeypatch, GAP_MINT)

    async def _rejected(self, token, query, params):
        return _envelope('{"status": "error", "error": "timeout"}')

    monkeypatch.setattr(CortexGapReader, "_execute_query", _rejected)

    rows = await reader.read_recurring_gaps(
        org_id="org-1", org_name="Acme", requisition_id="req-1"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_gap_malformed_envelope_returns_empty(monkeypatch):
    reader = CortexGapReader()
    _patch_mint(monkeypatch, GAP_MINT)

    async def _junk(self, token, query, params):
        return _envelope("this is not json")

    monkeypatch.setattr(CortexGapReader, "_execute_query", _junk)

    rows = await reader.read_recurring_gaps(
        org_id="org-1", org_name="Acme", requisition_id="req-1"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_gap_token_mint_failure_returns_empty(monkeypatch):
    reader = CortexGapReader()

    def _boom(*, org_id, org_name):
        raise RuntimeError("no signing key configured")

    monkeypatch.setattr(GAP_MINT, _boom)

    async def _should_not_run(self, token, query, params):
        raise AssertionError("query attempted despite token-mint failure")

    monkeypatch.setattr(CortexGapReader, "_execute_query", _should_not_run)

    rows = await reader.read_recurring_gaps(
        org_id="org-1", org_name="Acme", requisition_id="req-1"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_gap_transport_error_returns_empty(monkeypatch):
    reader = CortexGapReader()
    _patch_mint(monkeypatch, GAP_MINT)

    async def _raise(self, token, query, params):
        raise httpx.ReadTimeout("slow cortex")

    monkeypatch.setattr(CortexGapReader, "_execute_query", _raise)

    rows = await reader.read_recurring_gaps(
        org_id="org-1", org_name="Acme", requisition_id="req-1"
    )
    assert rows == []


# --------------------------------------------------------------------------- #
# REAL _execute_query transport — JSON and SSE JSON-RPC parse paths           #
# (respx mocks only the raw /mcp POST, so the actual unwrap logic runs).       #
# --------------------------------------------------------------------------- #


def _mcp_url():
    from app.config import get_settings

    return get_settings().CORTEX_MCP_URL.rstrip("/") + "/mcp"


@pytest.mark.asyncio
async def test_execute_query_unwraps_plain_json(monkeypatch, respx_mock):
    """content-type application/json -> response.json() returned verbatim, then
    _parse_rows pulls the data rows out."""
    reader = CortexPersonaReader()
    _patch_mint(monkeypatch, PERSONA_MINT)

    body = _envelope(
        '{"status": "ok", "data": ['
        '{"trait": "Decisive", "category": "style",'
        ' "evidence": "moves fast", "frequency": 2}]}'
    )
    respx_mock.post(_mcp_url()).mock(
        return_value=httpx.Response(
            200, json=body, headers={"content-type": "application/json"}
        )
    )

    rows = await reader.read_interviewer_signal(
        org_id="org-1", org_name="Acme", role_title="Eng"
    )
    assert rows[0]["trait"] == "Decisive"


@pytest.mark.asyncio
async def test_execute_query_unwraps_sse_jsonrpc(monkeypatch, respx_mock):
    """content-type text/event-stream -> _parse_sse_jsonrpc extracts the data
    line's JSON-RPC body, then _parse_rows pulls the rows out."""
    reader = CortexGapReader()
    _patch_mint(monkeypatch, GAP_MINT)

    inner = (
        '{"jsonrpc": "2.0", "id": 1, "result": {"content": [{"text": '
        '"{\\"status\\": \\"ok\\", \\"data\\": '
        '[{\\"competency\\": \\"System Design\\", \\"weak_candidates\\": 5}]}"}]}}'
    )
    sse_body = f"event: message\ndata: {inner}\n\n"
    respx_mock.post(_mcp_url()).mock(
        return_value=httpx.Response(
            200,
            content=sse_body.encode(),
            headers={"content-type": "text/event-stream"},
        )
    )

    rows = await reader.read_recurring_gaps(
        org_id="org-1", org_name="Acme", requisition_id="req-1"
    )
    assert rows == [{"competency": "System Design", "weak_candidates": 5}]


@pytest.mark.asyncio
async def test_execute_query_http_error_returns_empty(monkeypatch, respx_mock):
    """A non-2xx from the MCP server -> raise_for_status raises -> the reader's
    best-effort guard collapses it to []."""
    reader = CortexPersonaReader()
    _patch_mint(monkeypatch, PERSONA_MINT)

    respx_mock.post(_mcp_url()).mock(return_value=httpx.Response(503))

    rows = await reader.read_interviewer_signal(
        org_id="org-1", org_name="Acme", role_title="Eng"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_execute_query_sse_without_data_line_returns_empty(
    monkeypatch, respx_mock
):
    """An SSE body with no `data:` line -> _parse_sse_jsonrpc raises ValueError
    -> caught by the reader -> []."""
    reader = CortexGapReader()
    _patch_mint(monkeypatch, GAP_MINT)

    respx_mock.post(_mcp_url()).mock(
        return_value=httpx.Response(
            200,
            content=b"event: message\n\n",
            headers={"content-type": "text/event-stream"},
        )
    )

    rows = await reader.read_recurring_gaps(
        org_id="org-1", org_name="Acme", requisition_id="req-1"
    )
    assert rows == []
