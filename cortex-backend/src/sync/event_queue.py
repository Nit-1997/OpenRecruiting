"""cortex_events as a work queue.

The table has always been the durable ledger; SQS only carried rows out of it
to a consumer in the same process. This is the whole queue: claim a leased
batch, mark done, mark failed. Nothing here knows what an event means.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_ERROR_MAX = 500


@dataclass(frozen=True)
class ClaimedEvent:
    id: str
    event_type: str
    source_id: str
    org_id: str
    last_touch_at: datetime
    publish_count: int


class EventQueue:
    def __init__(self, supabase: Any, lease_seconds: int = 300, max_attempts: int = 5):
        self._sb = supabase
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        """Callers compare a claimed row's (post-increment) publish_count against
        this to tell a retry apart from the last attempt the row will ever get."""
        return self._max_attempts

    async def claim_batch(
        self,
        limit: int,
        cutoff: datetime | None,
        org_id: str | None = None,
    ) -> list[ClaimedEvent]:
        """Lease up to `limit` eligible rows. `cutoff=None` ignores the
        settledness window, which is what force-publish wants."""
        resp = await self._sb.rpc(
            "cortex_events_claim_batch",
            {
                "p_cutoff": cutoff.isoformat() if cutoff else None,
                "p_lease_seconds": self._lease_seconds,
                "p_max_attempts": self._max_attempts,
                "p_limit": limit,
                "p_org_id": org_id,
            },
        ).execute()
        return [
            ClaimedEvent(
                id=str(r["id"]),
                event_type=r["event_type"],
                source_id=str(r["source_id"]),
                org_id=str(r["org_id"]),
                last_touch_at=datetime.fromisoformat(r["last_touch_at"]),
                publish_count=int(r["publish_count"]),
            )
            for r in (resp.data or [])
        ]

    async def mark_done(self, event_id: str, completed_through: datetime) -> None:
        """`completed_through` is the claimed row's own last_touch_at, not the
        wall clock: an edit landing mid-processing would otherwise predate a
        now() stamp and never re-queue. Equal timestamps keep the row
        ineligible; a real edit makes last_touch_at strictly greater."""
        # publish_count resets so a later re-edit starts with a full retry
        # budget; without this a long-lived row eventually parks itself.
        await (
            self._sb.table("cortex_events")
            .update({
                "completed_at": completed_through.isoformat(),
                "last_error": None,
                "publish_count": 0,
            })
            .eq("id", event_id)
            .execute()
        )

    async def mark_failed(self, event_id: str, error: str) -> None:
        """Leave completed_at unset so the row returns once its lease expires,
        until publish_count reaches max_attempts and the claim query parks it."""
        await (
            self._sb.table("cortex_events")
            .update({"last_error": error[:_ERROR_MAX]})
            .eq("id", event_id)
            .execute()
        )
