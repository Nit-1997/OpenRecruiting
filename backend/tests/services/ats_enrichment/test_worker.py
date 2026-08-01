"""drain_enrichment_once: active-first selection, per-candidate isolation, the
status transitions (skipped / retry / park). The processor is injected as `process`."""

import json

from tests.helpers.supabase_mocks import mock_select, mock_update

from app.services.ats_enrichment import worker
from app.services.supabase import get_supabase_admin_client


def cand(cid, status="active", attempts=0):
    return {
        "id": cid,
        "requisition_id": "r1",
        "name": "X",
        "status": status,
        "profile": None,
        "enrichment_attempts": attempts,
    }


async def test_active_processed_before_others(respx_mock):
    # default batch = 1 → the active-first stable sort must pick the active row
    mock_select(respx_mock, "candidates", [cand("rej", "rejected"), cand("act", "active")])
    seen: list[str] = []

    async def fake(_sb, row):
        seen.append(row["id"])
        return "done"

    handled = await worker.drain_enrichment_once(get_supabase_admin_client(), process=fake)
    assert handled == 1
    assert seen == ["act"]


async def test_skipped_marks_skipped(respx_mock):
    mock_select(respx_mock, "candidates", [cand("c1")])
    upd = mock_update(respx_mock, "candidates")

    async def fake(_sb, _row):
        return "skipped"

    handled = await worker.drain_enrichment_once(get_supabase_admin_client(), process=fake)
    assert handled == 1
    sent = json.loads(upd.calls[0].request.content)
    assert sent["enrichment_status"] == "skipped"


async def test_done_does_not_touch_candidate(respx_mock):
    # 'done' status is set by the ats_enrich_candidate RPC inside the processor —
    # the worker must NOT issue an extra candidates update.
    mock_select(respx_mock, "candidates", [cand("c1")])
    upd = mock_update(respx_mock, "candidates")

    async def fake(_sb, _row):
        return "done"

    handled = await worker.drain_enrichment_once(get_supabase_admin_client(), process=fake)
    assert handled == 1
    assert upd.call_count == 0


async def test_failure_parks_at_max_retries(respx_mock):
    # attempts 4 + this failure = 5 == default ATS_ENRICHMENT_MAX_RETRIES → parked
    mock_select(respx_mock, "candidates", [cand("c1", attempts=4)])
    upd = mock_update(respx_mock, "candidates")

    async def fake(_sb, _row):
        raise RuntimeError("boom")

    handled = await worker.drain_enrichment_once(get_supabase_admin_client(), process=fake)
    assert handled == 0
    sent = json.loads(upd.calls[0].request.content)
    assert sent["enrichment_attempts"] == 5
    assert sent["enrichment_status"] == "failed"
    assert sent["enrichment_error"] == "boom"


async def test_failure_below_max_stays_pending(respx_mock):
    mock_select(respx_mock, "candidates", [cand("c1", attempts=0)])
    upd = mock_update(respx_mock, "candidates")

    async def fake(_sb, _row):
        raise RuntimeError("transient")

    handled = await worker.drain_enrichment_once(get_supabase_admin_client(), process=fake)
    assert handled == 0
    sent = json.loads(upd.calls[0].request.content)
    assert sent["enrichment_attempts"] == 1
    assert "enrichment_status" not in sent  # stays pending for the next pass
