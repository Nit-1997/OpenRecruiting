"""Tests for the proactive "add a screen?" suggestion service.

Two seams keep these tests network-free:
  - CortexGapReader.read_recurring_gaps   (the whole Cortex read)
  - the fake Supabase client               (rounds + enabled-config reads)

The service must be FAIL SAFE: cold start, empty Cortex, an already-enabled
screen, or any reader exception all collapse to should_suggest=False without
raising. Mirrors the seam-mock style in test_persona_reduce.py.
"""

import pytest

from app.api.v2.services.cortex_gap_reader import CortexGapReader
from app.api.v2.services.screening_suggestion_service import (
    ScreeningSuggestionService,
)


# --------------------------------------------------------------------------- #
# Fake Supabase client (rounds + round_screening_configs reads)               #
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """Records .eq filters and returns the table's canned rows on await."""

    def __init__(self, rows, order_calls):
        self._rows = rows
        self._order_calls = order_calls

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def is_null(self, *_a, **_k):
        return self

    def order(self, col, **kwargs):
        # Mirror the DB's ORDER BY so the service can trust row[0] is the first
        # round. desc honored for parity, though the service orders ascending.
        self._order_calls.append((col, kwargs))
        self._rows = sorted(
            self._rows,
            key=lambda r: r.get(col),
            reverse=bool(kwargs.get("desc")),
        )
        return self

    async def execute_async(self):
        return _FakeResponse(self._rows)


class _FakeSupabase:
    def __init__(self, *, rounds=None, enabled_configs=None):
        self._rounds = rounds if rounds is not None else []
        self._enabled_configs = enabled_configs if enabled_configs is not None else []
        self.order_calls = []

    def table(self, name):
        if name == "rounds":
            return _FakeQuery(self._rounds, self.order_calls)
        if name == "round_screening_configs":
            return _FakeQuery(self._enabled_configs, self.order_calls)
        raise AssertionError(f"unexpected table {name}")


def _rounds(*numbers):
    return [
        {"id": f"round-{n}", "round_number": n, "name": f"Round {n}"} for n in numbers
    ]


# --------------------------------------------------------------------------- #
# should_suggest = True (recurring gap, no screen yet)                         #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_suggest_true_on_recurring_gap(monkeypatch):
    async def _fake_read(self, *, org_id, org_name, requisition_id):
        assert requisition_id == "req-1"
        return [
            {"competency": "System Design", "weak_candidates": 3},
            {"competency": "Communication", "weak_candidates": 2},
        ]

    monkeypatch.setattr(CortexGapReader, "read_recurring_gaps", _fake_read)

    supabase = _FakeSupabase(rounds=_rounds(2, 1, 3), enabled_configs=[])
    service = ScreeningSuggestionService(supabase)

    result = await service.suggest(
        requisition_id="req-1", org_id="org-1", org_name="Acme"
    )

    assert result["should_suggest"] is True
    # The dominant gap drives the human-readable reason.
    assert "System Design" in result["reason"]
    assert "3" in result["reason"]
    # Targets the first round (lowest round_number) to catch it earliest.
    assert result["target_round_id"] == "round-1"


# --------------------------------------------------------------------------- #
# should_suggest = False (cold start / empty Cortex)                          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_no_suggest_on_empty_cortex(monkeypatch):
    async def _empty(self, *, org_id, org_name, requisition_id):
        return []

    monkeypatch.setattr(CortexGapReader, "read_recurring_gaps", _empty)

    supabase = _FakeSupabase(rounds=_rounds(1, 2), enabled_configs=[])
    result = await ScreeningSuggestionService(supabase).suggest(
        requisition_id="req-1", org_id="org-1", org_name="Acme"
    )

    assert result["should_suggest"] is False
    assert result["target_round_id"] is None


# --------------------------------------------------------------------------- #
# should_suggest = False (single candidate = not a pattern)                   #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_no_suggest_below_threshold(monkeypatch):
    async def _thin(self, *, org_id, org_name, requisition_id):
        return [{"competency": "System Design", "weak_candidates": 1}]

    monkeypatch.setattr(CortexGapReader, "read_recurring_gaps", _thin)

    supabase = _FakeSupabase(rounds=_rounds(1, 2), enabled_configs=[])
    result = await ScreeningSuggestionService(supabase).suggest(
        requisition_id="req-1", org_id="org-1", org_name="Acme"
    )

    assert result["should_suggest"] is False


# --------------------------------------------------------------------------- #
# should_suggest = False (screen already enabled → suppress)                  #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_suppressed_when_screen_already_enabled(monkeypatch):
    # Cortex WOULD suggest, but a screen is already enabled on a round.
    async def _gap(self, *, org_id, org_name, requisition_id):
        return [{"competency": "System Design", "weak_candidates": 4}]

    monkeypatch.setattr(CortexGapReader, "read_recurring_gaps", _gap)

    supabase = _FakeSupabase(
        rounds=_rounds(1, 2),
        enabled_configs=[{"id": "cfg-1", "round_id": "round-1", "enabled": True}],
    )
    result = await ScreeningSuggestionService(supabase).suggest(
        requisition_id="req-1", org_id="org-1", org_name="Acme"
    )

    assert result["should_suggest"] is False


# --------------------------------------------------------------------------- #
# should_suggest = False (reader raises → never propagate)                    #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_no_suggest_when_reader_raises(monkeypatch):
    async def _boom(self, *, org_id, org_name, requisition_id):
        raise RuntimeError("cortex down")

    monkeypatch.setattr(CortexGapReader, "read_recurring_gaps", _boom)

    supabase = _FakeSupabase(rounds=_rounds(1), enabled_configs=[])
    result = await ScreeningSuggestionService(supabase).suggest(
        requisition_id="req-1", org_id="org-1", org_name="Acme"
    )

    assert result["should_suggest"] is False
    assert result["target_round_id"] is None


# --------------------------------------------------------------------------- #
# should_suggest = False (gap exists but role has no rounds)                  #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_no_suggest_when_no_rounds(monkeypatch):
    async def _gap(self, *, org_id, org_name, requisition_id):
        return [{"competency": "System Design", "weak_candidates": 3}]

    monkeypatch.setattr(CortexGapReader, "read_recurring_gaps", _gap)

    supabase = _FakeSupabase(rounds=[], enabled_configs=[])
    result = await ScreeningSuggestionService(supabase).suggest(
        requisition_id="req-1", org_id="org-1", org_name="Acme"
    )

    assert result["should_suggest"] is False
    assert result["target_round_id"] is None


# --------------------------------------------------------------------------- #
# Reader — defensive parsing (reuses the MCP seam)                            #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reader_empty_on_mcp_error(monkeypatch):
    reader = CortexGapReader()

    async def _raise(self, token, query, params):
        raise RuntimeError("boom")

    monkeypatch.setattr(CortexGapReader, "_execute_query", _raise)
    monkeypatch.setattr(
        "app.api.v2.services.cortex_gap_reader.mint_cortex_service_token",
        lambda *, org_id, org_name: ("tok", 300),
    )

    rows = await reader.read_recurring_gaps(
        org_id="org-1", org_name="Acme", requisition_id="req-1"
    )
    assert rows == []


@pytest.mark.asyncio
async def test_reader_parses_rows(monkeypatch):
    reader = CortexGapReader()

    async def _ok(self, token, query, params):
        assert params["req_ref"] == "req-1"
        return {
            "result": {
                "content": [
                    {
                        "text": (
                            '{"status": "ok", "data": ['
                            '{"competency": "System Design", "weak_candidates": 3}]}'
                        )
                    }
                ]
            }
        }

    monkeypatch.setattr(CortexGapReader, "_execute_query", _ok)
    monkeypatch.setattr(
        "app.api.v2.services.cortex_gap_reader.mint_cortex_service_token",
        lambda *, org_id, org_name: ("tok", 300),
    )

    rows = await reader.read_recurring_gaps(
        org_id="org-1", org_name="Acme", requisition_id="req-1"
    )
    assert len(rows) == 1
    assert rows[0]["competency"] == "System Design"
    assert rows[0]["weak_candidates"] == 3
