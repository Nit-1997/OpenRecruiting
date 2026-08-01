"""One-time backfill: bulk-insert cortex_events rows for historical settled data.

Usage:
    python -m scripts.cortex_backfill --org-id <org-uuid>
    python -m scripts.cortex_backfill --all-orgs

Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in env.
"""
import argparse
import asyncio
import os
import sys

import structlog
from supabase import create_async_client

logger = structlog.get_logger(__name__)


_BACKFILL_QUERIES = {
    "feedback_debrief_available": """
        INSERT INTO cortex_events (event_type, source_id, org_id, source_table, last_touch_at)
        SELECT
          'feedback_debrief_available',
          cr.id,
          r.organization_id,
          'backfill',
          COALESCE(cr.processing_completed_at, cr.updated_at)
        FROM candidate_rounds cr
        JOIN rounds rnd ON rnd.id = cr.round_id
        JOIN requisitions r ON r.id = rnd.requisition_id
        WHERE r.organization_id = $1
          AND cr.processing_status = 'completed'
          AND COALESCE(cr.processing_completed_at, cr.updated_at) < now() - interval '48 hours'
        ON CONFLICT (event_type, source_id) DO NOTHING;
    """,
    "intake_transcript_available": """
        INSERT INTO cortex_events (event_type, source_id, org_id, source_table, last_touch_at)
        SELECT
          'intake_transcript_available',
          r.id,
          r.organization_id,
          'backfill',
          COALESCE(r.intake_processing_completed_at, r.updated_at)
        FROM requisitions r
        WHERE r.organization_id = $1
          AND r.intake_processing_status = 'completed'
          AND COALESCE(r.intake_processing_completed_at, r.updated_at) < now() - interval '48 hours'
        ON CONFLICT (event_type, source_id) DO NOTHING;
    """,
    "decision_made": """
        INSERT INTO cortex_events (event_type, source_id, org_id, source_table, last_touch_at)
        SELECT
          'decision_made',
          c.id,
          r.organization_id,
          'backfill',
          c.updated_at
        FROM candidates c
        JOIN requisitions r ON r.id = c.requisition_id
        WHERE r.organization_id = $1
          AND c.final_verdict IS NOT NULL
          AND c.updated_at < now() - interval '48 hours'
        ON CONFLICT (event_type, source_id) DO NOTHING;
    """,
}


async def backfill_org(org_id: str) -> dict:
    client = await create_async_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    )
    counts = {}
    for event_type, sql in _BACKFILL_QUERIES.items():
        # Run via execute_readonly_query won't work for INSERT; use raw rpc to a helper
        # or supabase-py direct. The simplest path: call mcp__supabase__execute_sql at deploy time.
        # Below assumes a server-side function `cortex_backfill_event` accepting (event_type, org_id).
        await client.rpc(
            "cortex_backfill_org_event",
            {"event_type": event_type, "org_id": org_id},
        ).execute()
        counts[event_type] = "ok"
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--org-id", help="Backfill a single org")
    parser.add_argument("--all-orgs", action="store_true", help="Backfill all orgs")
    args = parser.parse_args()

    if not args.org_id and not args.all_orgs:
        parser.error("Provide --org-id <uuid> or --all-orgs")

    if args.org_id:
        result = asyncio.run(backfill_org(args.org_id))
        print(result)
    else:
        print("All-orgs backfill: implement org enumeration; intentional stub.")


if __name__ == "__main__":
    sys.exit(main() or 0)
