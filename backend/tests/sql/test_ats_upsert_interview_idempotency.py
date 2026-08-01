"""DEV-DB integration: ats_upsert_interview is idempotent on
(organization_id, ats_interview_event_id) — same event twice → ONE row.

Gated: requires a real DEV Supabase + a seeded org/connection. Run with
  ATS_SQL_LIVE=1 ATS_SQL_ORG=<org_uuid> ATS_SQL_CONN=<connection_uuid> \
  python -m pytest tests/sql/test_ats_upsert_interview_idempotency.py -v
Skipped otherwise (and in the Docker CI image)."""

import os
import uuid

import pytest

# Phase A constraint: migration 129 is written but NOT applied to the DB by the
# implementer (the orchestrator applies it to DEV via the Supabase MCP). Keep the
# suite green by skipping unconditionally until then; the orchestrator removes
# this marker (or runs with ATS_SQL_LIVE=1) once 129 is live.
pytestmark = [
    pytest.mark.skip(
        reason="requires migration 129 applied to dev — run by orchestrator"
    ),
    pytest.mark.skipif(
        os.environ.get("ATS_SQL_LIVE") != "1",
        reason="DEV-DB live test; set ATS_SQL_LIVE=1 + ATS_SQL_ORG + ATS_SQL_CONN",
    ),
]


def _client():
    from supabase import create_client  # supabase-py is available in the env for this live path

    return create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"]
    )


def test_same_event_twice_yields_one_row():
    org = os.environ["ATS_SQL_ORG"]
    conn = os.environ["ATS_SQL_CONN"]
    event_id = f"phase-a-test-{uuid.uuid4()}"
    client = _client()
    fields = {
        "ats_interview_event_id": event_id,
        "ats_application_id": "app-test",
        "stage_name": "Technical Screen",
        "interview_title": "System Design",
        "status": "Scheduled",
        "interviewers": [{"email": "ada@example.com", "name": "Ada Lovelace", "ats_user_id": "user-1"}],
        "provider": "ashby",
    }

    r1 = client.rpc("ats_upsert_interview", {"p_org": org, "p_connection": conn, "p_fields": fields}).execute()
    r2 = client.rpc("ats_upsert_interview", {"p_org": org, "p_connection": conn, "p_fields": fields}).execute()

    assert r1.data["action"] == "inserted"
    assert r2.data["action"] == "updated"
    assert r1.data["id"] == r2.data["id"]

    rows = (
        client.table("ats_interviews")
        .select("id")
        .eq("organization_id", org)
        .eq("ats_interview_event_id", event_id)
        .execute()
    )
    assert len(rows.data) == 1

    client.table("ats_interviews").delete().eq("id", r1.data["id"]).execute()
