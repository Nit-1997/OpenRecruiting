"""
Backfill episodic data for existing candidate_rounds and requisitions.

Usage:
    python3 -m scripts.backfill_episodic --source question_summaries --org-id <org> --dry-run
    python3 -m scripts.backfill_episodic --source all --org-id <org>
"""
import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

logger = structlog.get_logger(__name__)

SOURCE_ORDER = ["question_summaries", "intake", "feedback_debrief", "interview", "jd"]

EVENT_TYPE_MAP = {
    "question_summaries": "question_summaries_available",
    "intake": "intake_transcript_available",
    "feedback_debrief": "feedback_debrief_available",
    "interview": "interview_transcript_available",
    "jd": "jd_available",
}


async def fetch_backfill_targets(client, source: str, org_id: str) -> list[dict]:
    if source in ("question_summaries", "feedback_debrief", "interview"):
        resp = await client.table("candidate_rounds").select(
            "id, candidate_id, round_id, rounds!inner(requisition_id, requisitions!inner(organization_id))"
        ).eq("rounds.requisitions.organization_id", org_id).execute()
        return [
            {"candidate_round_id": r["id"], "requisition_id": r["rounds"]["requisition_id"]}
            for r in (resp.data or [])
        ]
    elif source in ("intake", "jd"):
        resp = await client.table("requisitions").select("id").eq("organization_id", org_id).execute()
        return [{"requisition_id": r["id"]} for r in (resp.data or [])]
    return []


async def run_backfill(source: str, org_id: str, dry_run: bool = False):
    from supabase import acreate_client
    from src.config.settings import get_settings
    settings = get_settings()
    client = await acreate_client(settings.supabase.url, settings.supabase.service_role_key)

    targets = await fetch_backfill_targets(client, source, org_id)
    event_type = EVENT_TYPE_MAP[source]
    backfill_run_id = str(uuid.uuid4())[:8]

    logger.info("backfill_start", source=source, org_id=org_id, target_count=len(targets), backfill_run_id=backfill_run_id, dry_run=dry_run)

    if dry_run:
        for t in targets[:5]:
            logger.info("backfill_dry_run_target", target=t, event_type=event_type)
        logger.info("backfill_dry_run_complete", total=len(targets), shown=min(5, len(targets)))
        return

    import httpx
    api_url = "http://localhost:8010/api/v1/ingest"
    success = 0
    errors = 0
    async with httpx.AsyncClient(timeout=120.0) as http:
        for i, target in enumerate(targets):
            source_ref = {}
            if "candidate_round_id" in target:
                source_ref["candidate_round_id"] = target["candidate_round_id"]
            if "requisition_id" in target:
                source_ref["requisition_id"] = target["requisition_id"]
            payload = {
                "event_type": event_type,
                "org_id": org_id,
                "source_ref": source_ref,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            try:
                resp = await http.post(api_url, json=payload, headers={"X-Internal-Secret": settings.auth.internal_secret})
                data = resp.json()
                if resp.status_code == 200:
                    success += 1
                    logger.info("backfill_ok", i=i + 1, total=len(targets), status=data.get("status"), nodes=data.get("nodes_created"))
                else:
                    errors += 1
                    logger.warning("backfill_error", i=i + 1, status_code=resp.status_code, detail=data)
            except Exception as e:
                errors += 1
                logger.error("backfill_exception", i=i + 1, error=str(e))

    logger.info("backfill_complete", source=source, success=success, errors=errors, total=len(targets), backfill_run_id=backfill_run_id)


async def main():
    parser = argparse.ArgumentParser(description="Backfill episodic data")
    parser.add_argument("--source", required=True, choices=SOURCE_ORDER + ["all"])
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sources = SOURCE_ORDER if args.source == "all" else [args.source]
    for source in sources:
        await run_backfill(source, args.org_id, args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
