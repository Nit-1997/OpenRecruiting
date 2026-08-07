# Cortex Ingestion Without SQS, and Honest Defaults — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Cortex knowledge-graph ingestion work on a plain `docker compose up` by replacing the never-configured SQS queue with Postgres-backed claim/process, then delete the Slack assistant and calendar intelligence and turn the remaining feature defaults on.

**Architecture:** `cortex_events` is already a durable Postgres ledger. A new `SECURITY DEFINER` RPC claims a batch with `FOR UPDATE SKIP LOCKED`; a thin `EventQueue` wraps it; the existing consumer becomes `EventProcessor` with its transport-decoding head removed and its ~100-line ingestion body untouched. `BrainSyncCron` claims and processes inline instead of publishing to SQS.

**Tech Stack:** Python 3.11, FastAPI, APScheduler, supabase-py (REST client only — no asyncpg/psycopg), Neo4j, Postgres (Supabase), pytest.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-06-cortex-queue-and-defaults-design.md`.
- **Branch:** `feat/admin-portal-and-stack-fixes`. Do not push.
- **No new containers, no new runtime dependencies.** boto3 usage in cortex-backend goes to zero.
- **cortex-backend has no raw Postgres driver.** All SQL runs through `supabase.rpc(...)` or `supabase.table(...)`. Anything needing `FOR UPDATE SKIP LOCKED` must be a Postgres function.
- **CI debrand gate:** no file content or filename may contain the pre-open-source brand name (`git ls-files | grep -i mazle` must be empty).
- **Never commit** `.env`, API keys, certificates, or private keys.
- **Run `make test` before every commit** that touches `backend/`. Run cortex-backend's suite for `cortex-backend/` changes.
- Existing baselines to preserve: **2909** backend tests passing, **~440** cortex-backend tests.
- Every HTML element added anywhere in this project gets a unique `id`.
- Keep comments minimal; explain *why*, never restate *what*.

---

## File Structure

| File | Responsibility |
|---|---|
| `schema.sql` | Adds `cortex_events.completed_at` and the `cortex_events_claim_batch` RPC. |
| `cortex-backend/src/sync/event_queue.py` | **New.** Claim/complete/fail against `cortex_events`. Pure queue mechanics, no domain knowledge. |
| `cortex-backend/src/sync/event_processor.py` | **New (from `sqs_consumer.py`).** Ingests one claimed row. All existing ingestion logic, minus transport. |
| `cortex-backend/src/sync/sqs_consumer.py` | **Deleted.** |
| `cortex-backend/src/sync/brain_sync_cron.py` | Drives `EventQueue` + `EventProcessor`; no SQS. |
| `cortex-backend/src/main.py` | Wires the above; drops boto3 and the `SqsConsumer` task. |
| `cortex-backend/src/config/settings.py` | Sync tuning: lease, batch, poll interval; drops SQS/AWS fields. |
| `backend/app/config.py` | Feature defaults; removes deleted-feature settings. |
| `docs/architecture.md`, `.env.example`, `README.md` | Made truthful. |

**Task → commit mapping.** Tasks 1–4 are spec commit 1 (queue swap), Tasks 5–6 are commit 2 (deletions), Task 7 is commit 3 (defaults and docs). Each task commits on its own so a reviewer can reject one without unwinding its neighbours.

---

### Task 1: Schema — claim column and claim RPC

**Files:**
- Modify: `schema.sql` (append to the cortex function block near line 1736, and the ACL block near line 9005)
- Apply: the same SQL to the running Supabase project via MCP `apply_migration`

**Interfaces:**
- Consumes: nothing.
- Produces: `public.cortex_events.completed_at timestamptz NULL`, and
  `public.cortex_events_claim_batch(p_cutoff timestamptz, p_lease_seconds integer, p_max_attempts integer, p_limit integer, p_org_id uuid) RETURNS TABLE(id uuid, event_type text, source_id uuid, org_id uuid, last_touch_at timestamptz, publish_count integer)`.

**Why a column is needed.** Completion is recorded in `cortex_ingestion_record`, a different table. `cortex_events` alone therefore cannot tell "claimed and finished" from "claimed and then crashed", and the existing predicate `published_at IS NULL OR last_touch_at > published_at` makes a crashed claim look permanently done — recoverable only by the weekly reconcile. `completed_at` lets an expired lease recover it in minutes.

- [ ] **Step 1: Write the SQL**

Append to `schema.sql` immediately after the `cortex_events_settled` function:

```sql
--
-- Name: cortex_events_claim_batch(...); Type: FUNCTION; Schema: public; Owner: -
--
-- Atomically leases a batch of pending events. FOR UPDATE SKIP LOCKED is the
-- only reason this is a function: cortex-backend reaches Postgres through the
-- Supabase REST client and cannot express row locking from Python.
--
-- Eligible rows are unfinished (or edited since finishing), under the attempt
-- cap, and either never claimed or holding an expired lease. Claiming stamps
-- published_at as the lease start and clears last_error so a retry does not
-- inherit the previous failure's message.

CREATE FUNCTION public.cortex_events_claim_batch(p_cutoff timestamp with time zone, p_lease_seconds integer, p_max_attempts integer, p_limit integer, p_org_id uuid DEFAULT NULL) RETURNS TABLE(id uuid, event_type text, source_id uuid, org_id uuid, last_touch_at timestamp with time zone, publish_count integer)
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
  RETURN QUERY
  UPDATE public.cortex_events e
     SET published_at  = now(),
         publish_count = e.publish_count + 1,
         last_error    = NULL
   WHERE e.id IN (
       SELECT c.id
         FROM public.cortex_events c
        WHERE (p_org_id IS NULL OR c.org_id = p_org_id)
          AND (p_cutoff IS NULL OR c.last_touch_at < p_cutoff)
          AND c.publish_count < p_max_attempts
          AND (c.completed_at IS NULL OR c.last_touch_at > c.completed_at)
          AND (c.published_at IS NULL
               OR c.published_at < now() - make_interval(secs => p_lease_seconds))
        ORDER BY c.last_touch_at ASC
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
   )
  RETURNING e.id, e.event_type, e.source_id, e.org_id, e.last_touch_at, e.publish_count;
END;
$$;
```

Add the column to the `cortex_events` CREATE TABLE (after `last_error`):

```sql
    completed_at timestamp with time zone,
```

Add a partial index next to the table's other indexes:

```sql
CREATE INDEX cortex_events_pending_idx ON public.cortex_events USING btree (last_touch_at) WHERE (completed_at IS NULL);
```

Add the ACL beside the other cortex function grants. Unlike the neighbouring
functions, this one is **not** granted to `anon`/`authenticated`: it mutates the
queue, only cortex-backend (service_role) calls it, and no RLS policy references
it — so the narrow grant is safe. (`is_admin()` is the counter-example: it *is*
called from 39 policies and must keep its `authenticated` grant.)

```sql
REVOKE ALL ON FUNCTION public.cortex_events_claim_batch(p_cutoff timestamp with time zone, p_lease_seconds integer, p_max_attempts integer, p_limit integer, p_org_id uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cortex_events_claim_batch(p_cutoff timestamp with time zone, p_lease_seconds integer, p_max_attempts integer, p_limit integer, p_org_id uuid) TO service_role;
```

- [ ] **Step 2: Apply to the live database**

Use MCP `apply_migration` with name `cortex_events_claim_batch`, containing the
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS completed_at timestamp with time zone;`,
the `CREATE INDEX IF NOT EXISTS`, the `CREATE OR REPLACE FUNCTION`, and the
REVOKE/GRANT. Use `IF NOT EXISTS` / `OR REPLACE` in the applied version so it is
re-runnable, even though `schema.sql` keeps the plain `CREATE` form its
generator emits.

- [ ] **Step 3: Verify the claim actually leases**

Run via MCP `execute_sql`:

```sql
-- seed one eligible row
INSERT INTO public.cortex_events (event_type, source_id, org_id, source_table, last_touch_at)
VALUES ('plan_created', gen_random_uuid(), '00000000-0000-0000-0000-0000000000a1', 'requisitions', now() - interval '72 hours')
RETURNING id;

-- first claim returns it
SELECT count(*) AS first_claim
FROM public.cortex_events_claim_batch(now() - interval '48 hours', 300, 5, 10, NULL);

-- immediate second claim returns nothing: the lease is held
SELECT count(*) AS second_claim
FROM public.cortex_events_claim_batch(now() - interval '48 hours', 300, 5, 10, NULL);
```

Expected: `first_claim = 1`, `second_claim = 0`.

- [ ] **Step 4: Clean up the probe row**

```sql
DELETE FROM public.cortex_events WHERE event_type = 'plan_created' AND completed_at IS NULL AND publish_count = 1;
```

- [ ] **Step 5: Commit**

```bash
git add schema.sql
git commit -m "feat(db): add cortex_events.completed_at and a claim RPC

cortex-backend reaches Postgres only through the Supabase REST client, so
FOR UPDATE SKIP LOCKED has to live in a function. completed_at is needed
because completion is recorded in cortex_ingestion_record, a different table:
without it a claim that crashes looks permanently done and only the weekly
reconcile recovers it."
```

---

### Task 2: EventQueue

**Files:**
- Create: `cortex-backend/src/sync/event_queue.py`
- Test: `cortex-backend/tests/unit/test_event_queue.py`

**Interfaces:**
- Consumes: `cortex_events_claim_batch` from Task 1.
- Produces:
  - `class ClaimedEvent` with attributes `id: str`, `event_type: str`, `source_id: str`, `org_id: str`, `last_touch_at: datetime`, `publish_count: int`
  - `EventQueue(supabase, lease_seconds: int = 300, max_attempts: int = 5)`
  - `async claim_batch(limit: int, cutoff: datetime | None, org_id: str | None = None) -> list[ClaimedEvent]`
  - `async mark_done(event_id: str) -> None`
  - `async mark_failed(event_id: str, error: str) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# cortex-backend/tests/unit/test_event_queue.py
"""EventQueue is the only thing that knows cortex_events is a queue.

These are unit tests over a faked supabase client; the SKIP LOCKED behaviour
itself is exercised in the integration test in Task 4, because it cannot be
faked meaningfully.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.sync.event_queue import ClaimedEvent, EventQueue


class FakeResp:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, recorder, table):
        self._rec = recorder
        self._table = table
        self._update = None
        self._eq = {}

    def update(self, values):
        self._update = values
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    async def execute(self):
        self._rec.append({"table": self._table, "update": self._update, "eq": dict(self._eq)})
        return FakeResp([])


class FakeSupabase:
    def __init__(self, rpc_rows=None):
        self.rpc_rows = rpc_rows or []
        self.rpc_calls = []
        self.writes = []

    def rpc(self, name, params):
        self.rpc_calls.append({"name": name, "params": params})
        outer = self

        class _R:
            async def execute(self_inner):
                return FakeResp(outer.rpc_rows)

        return _R()

    def table(self, name):
        return FakeQuery(self.writes, name)


def _row(**over):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "event_type": "plan_created",
        "source_id": "22222222-2222-2222-2222-222222222222",
        "org_id": "33333333-3333-3333-3333-333333333333",
        "last_touch_at": "2026-08-01T00:00:00+00:00",
        "publish_count": 1,
    }
    base.update(over)
    return base


async def test_claim_batch_passes_lease_and_attempt_caps_to_the_rpc():
    sb = FakeSupabase(rpc_rows=[_row()])
    q = EventQueue(sb, lease_seconds=300, max_attempts=5)
    cutoff = datetime(2026, 8, 1, tzinfo=timezone.utc)

    events = await q.claim_batch(limit=10, cutoff=cutoff)

    call = sb.rpc_calls[0]
    assert call["name"] == "cortex_events_claim_batch"
    assert call["params"]["p_lease_seconds"] == 300
    assert call["params"]["p_max_attempts"] == 5
    assert call["params"]["p_limit"] == 10
    assert call["params"]["p_cutoff"] == cutoff.isoformat()
    assert call["params"]["p_org_id"] is None
    assert len(events) == 1
    assert isinstance(events[0], ClaimedEvent)
    assert events[0].event_type == "plan_created"
    assert events[0].last_touch_at == datetime(2026, 8, 1, tzinfo=timezone.utc)


async def test_claim_batch_scopes_to_org_and_drops_the_window_for_force_publish():
    sb = FakeSupabase(rpc_rows=[])
    q = EventQueue(sb)

    await q.claim_batch(limit=50, cutoff=None, org_id="33333333-3333-3333-3333-333333333333")

    params = sb.rpc_calls[0]["params"]
    assert params["p_cutoff"] is None
    assert params["p_org_id"] == "33333333-3333-3333-3333-333333333333"


async def test_mark_done_stamps_completion_and_resets_the_retry_budget():
    sb = FakeSupabase()
    q = EventQueue(sb)

    await q.mark_done("11111111-1111-1111-1111-111111111111")

    write = sb.writes[0]
    assert write["table"] == "cortex_events"
    assert write["eq"]["id"] == "11111111-1111-1111-1111-111111111111"
    assert write["update"]["completed_at"] is not None
    assert write["update"]["last_error"] is None
    # A later re-edit must get a fresh budget, or a healthy row eventually parks.
    assert write["update"]["publish_count"] == 0


async def test_mark_failed_records_a_truncated_error_and_leaves_completion_unset():
    sb = FakeSupabase()
    q = EventQueue(sb)

    await q.mark_failed("11111111-1111-1111-1111-111111111111", "boom " * 500)

    write = sb.writes[0]
    assert write["update"]["last_error"].startswith("boom")
    assert len(write["update"]["last_error"]) <= 500
    assert "completed_at" not in write["update"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec -T cortex-backend python -m pytest tests/unit/test_event_queue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.sync.event_queue'`

- [ ] **Step 3: Write the implementation**

```python
# cortex-backend/src/sync/event_queue.py
"""cortex_events as a work queue.

The table has always been the durable ledger; SQS only carried rows out of it
to a consumer in the same process. This is the whole queue: claim a leased
batch, mark done, mark failed. Nothing here knows what an event means.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
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

    async def mark_done(self, event_id: str) -> None:
        # publish_count resets so a later re-edit starts with a full retry
        # budget; without this a long-lived row eventually parks itself.
        await (
            self._sb.table("cortex_events")
            .update({
                "completed_at": datetime.now(timezone.utc).isoformat(),
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec -T cortex-backend python -m pytest tests/unit/test_event_queue.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add cortex-backend/src/sync/event_queue.py cortex-backend/tests/unit/test_event_queue.py
git commit -m "feat(cortex): add EventQueue over cortex_events

Claim/complete/fail against the ledger that was always there. Leasing replaces
the SQS visibility timeout; publish_count replaces the redelivery count and
gains an attempt cap, which is strictly better than today since nothing in the
repo ever configured a DLQ."
```

---

### Task 3: EventProcessor

**Files:**
- Create: `cortex-backend/src/sync/event_processor.py` (from `sqs_consumer.py`)
- Delete: `cortex-backend/src/sync/sqs_consumer.py`
- Create: `cortex-backend/tests/unit/test_event_processor.py` (from `test_sqs_consumer.py`)
- Delete: `cortex-backend/tests/unit/test_sqs_consumer.py`

**Interfaces:**
- Consumes: `ClaimedEvent` from Task 2.
- Produces: `EventProcessor(event_router, ingestion_repo, tombstone)` with
  `async process(event: ClaimedEvent) -> None`, raising `IngestionFailure` on a
  non-success handler status. `IngestionFailure` moves here from `sqs_consumer`.

**Method.** Copy `sqs_consumer.py` verbatim, then make exactly these changes.
Everything else — `_SOURCE_REF_KEY`, the staleness guard, tombstoning,
provenance, the handler call, the `IngestionRecord` upsert, the log lines — must
be **byte-identical**. Reviewers should be able to diff the two files and see
only transport removal.

1. Rename the class `SqsConsumer` → `EventProcessor`.
2. Constructor: drop `sqs_client`, `queue_url`, `max_messages`, `wait_seconds`,
   `visibility_timeout`, and `self._stop`. Keep `event_router`, `ingestion_repo`,
   `tombstone`.
3. Replace the `handle_message(self, raw: dict)` head:

```python
    async def handle_message(self, raw: dict) -> None:
        body = json.loads(raw["Body"])
        event_type: str = body["event_type"]
        source_id: str = body["source_id"]
        org_id: str = body["org_id"]
        incoming_touch = datetime.fromisoformat(body["last_touch_at"])
        event_pk: str = body["event_pk"]
```

   with:

```python
    async def process(self, event: ClaimedEvent) -> None:
        event_type = event.event_type
        source_id = event.source_id
        org_id = event.org_id
        incoming_touch = event.last_touch_at
        event_pk = event.id
```

4. In the `IngestionRecord` upsert, replace `publish_count=int(body.get("publish_count", 1))`
   with `publish_count=event.publish_count`.
5. Delete the entire `run()` method and `stop()`.
6. Drop the now-unused `import asyncio` and `import json`; add
   `from src.sync.event_queue import ClaimedEvent`.

- [ ] **Step 1: Port the test file**

```bash
git mv cortex-backend/tests/unit/test_sqs_consumer.py cortex-backend/tests/unit/test_event_processor.py
```

In the ported file: `SqsConsumer` → `EventProcessor`, constructor calls drop the
SQS arguments, and every fixture shaped like

```python
{"Body": json.dumps({"event_type": ..., "source_id": ..., "org_id": ...,
                     "last_touch_at": ..., "event_pk": ..., "publish_count": 1})}
```

becomes

```python
ClaimedEvent(id=..., event_type=..., source_id=..., org_id=...,
             last_touch_at=datetime.fromisoformat(...), publish_count=1)
```

with `consumer.handle_message(msg)` → `processor.process(event)`. Assertions do
not change, because the logic under test does not.

- [ ] **Step 2: Add a test for the field that changed meaning**

```python
async def test_publish_count_is_taken_from_the_claim_not_the_payload(processor_and_deps):
    """publish_count used to arrive in the SQS body; it now comes off the claim.
    IngestionRecord stores it as provenance, so a wrong source is silent."""
    processor, repo, _router = processor_and_deps

    await processor.process(ClaimedEvent(
        id="11111111-1111-1111-1111-111111111111",
        event_type="plan_created",
        source_id="22222222-2222-2222-2222-222222222222",
        org_id="33333333-3333-3333-3333-333333333333",
        last_touch_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        publish_count=3,
    ))

    assert repo.upserted[-1].publish_count == 3
```

Adapt `processor_and_deps` to whatever fixture the ported file already uses for
the router, repo and tombstone doubles; do not invent a new fixture style.

- [ ] **Step 3: Run to verify it fails**

Run: `docker compose exec -T cortex-backend python -m pytest tests/unit/test_event_processor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.sync.event_processor'`

- [ ] **Step 4: Create the module**

```bash
git mv cortex-backend/src/sync/sqs_consumer.py cortex-backend/src/sync/event_processor.py
```

Then apply changes 1–6 above.

- [ ] **Step 5: Run to verify it passes**

Run: `docker compose exec -T cortex-backend python -m pytest tests/unit/test_event_processor.py -v`
Expected: PASS

- [ ] **Step 6: Confirm the body really is unchanged**

Run: `git diff -M --stat HEAD -- cortex-backend/src/sync/`
Expected: the rename is detected as a rename with a small percentage changed. If
git does not detect it as a rename, too much was edited — re-check that only the
six documented changes were made.

- [ ] **Step 7: Commit**

```bash
git add -A cortex-backend/src/sync/ cortex-backend/tests/unit/
git commit -m "refactor(cortex): SqsConsumer becomes EventProcessor

Removes the transport head and the poll loop; the ~100 lines of ingestion
logic below them are untouched. process() takes a claimed row instead of an
SQS message, and publish_count now comes from the claim rather than a JSON
body field."
```

---

### Task 4: Wire the cron, delete SQS

**Files:**
- Modify: `cortex-backend/src/sync/brain_sync_cron.py`
- Modify: `cortex-backend/src/main.py:232-292`
- Modify: `cortex-backend/src/config/settings.py:56-66`
- Modify: `cortex-backend/src/controller/ingestion_controller.py:231` and `:300`
- Modify: `cortex-backend/tests/unit/test_brain_sync_cron.py`
- Create: `cortex-backend/tests/integration/test_ingestion_end_to_end.py`

**Interfaces:**
- Consumes: `EventQueue`, `ClaimedEvent` (Task 2); `EventProcessor` (Task 3).
- Produces: `BrainSyncCron(supabase, queue: EventQueue, processor: EventProcessor, settledness_window_hours: int = 48, batch_size: int = 1000)` with
  `async process_settled_events() -> int`, `async process_org_now(org_id: str, on_progress: ProgressCallback | None = None) -> dict`, `async reconcile() -> int`.

**Renames.** `publish_settled_events` → `process_settled_events`,
`publish_org_now` → `process_org_now`. Once nothing is published, "publish" is a
lie, and a name that outlives its meaning is the failure mode this whole branch
has been clearing up. Update both call sites in `ingestion_controller.py` and
the scheduler registration in `main.py`.

**Settings changes** in `config/settings.py`:

```python
    # was: publisher_interval_hours: int = 24
    poll_interval_seconds: int = 60
    # was: consumer_visibility_timeout: int = 300
    claim_lease_seconds: int = 300
    # was: consumer_max_messages: int = 10
    claim_batch_size: int = 10
    claim_max_attempts: int = 5
    # deleted: sqs_queue_url, aws_region, consumer_wait_seconds
    # unchanged: settledness_window_hours = 48, publish_batch_size = 1000
```

A 24h publisher interval would leave a newly settled row waiting up to another
day; eligibility is gated by the 48h window, not the poll rate.

- [ ] **Step 1: Write the failing integration test**

```python
# cortex-backend/tests/integration/test_ingestion_end_to_end.py
"""The test that would have caught the graph being empty.

Everything below the queue was already covered by unit tests; what was never
covered was whether anything reaches Neo4j at all.
"""
import pytest


@pytest.mark.integration
async def test_a_settled_event_reaches_neo4j(seeded_cortex_event, cron, neo4j_session, supabase):
    before = (await neo4j_session.run("MATCH (n) RETURN count(n) AS c")).single()["c"]

    processed = await cron.process_settled_events()

    assert processed == 1
    after = (await neo4j_session.run("MATCH (n) RETURN count(n) AS c")).single()["c"]
    assert after > before, "ingestion ran but wrote no nodes"

    row = await supabase.table("cortex_events").select("completed_at,last_error").eq(
        "id", seeded_cortex_event["id"]
    ).single().execute()
    assert row.data["completed_at"] is not None
    assert row.data["last_error"] is None


@pytest.mark.integration
async def test_a_failing_event_is_retried_then_parked(seeded_cortex_event, cron_with_failing_handler, supabase):
    # cron_with_failing_handler must be built with EventQueue(lease_seconds=0),
    # or the first claim blocks the next five for 300s. A zero lease belongs in
    # the fixture, not as a test-only parameter on the production method.
    for _ in range(6):
        await cron_with_failing_handler.process_settled_events()

    row = await supabase.table("cortex_events").select("publish_count,last_error,completed_at").eq(
        "id", seeded_cortex_event["id"]
    ).single().execute()
    assert row.data["completed_at"] is None
    assert row.data["last_error"] is not None
    assert row.data["publish_count"] <= 5, "attempt cap did not park the row"
```

`seeded_cortex_event` must insert a row with `last_touch_at = now() - 72h` so it
is past the 48h window, for an org and source that the handler can actually
resolve. Reuse whatever Neo4j and Supabase fixtures the existing integration
tests use; if `cortex-backend/tests/integration/` has no `conftest.py`, model the
fixtures on the ones in `tests/unit/conftest.py` and mark the module
`pytest.mark.integration` so it can be deselected without a live stack.

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec -T cortex-backend python -m pytest tests/integration/test_ingestion_end_to_end.py -v`
Expected: FAIL — `BrainSyncCron` has no `process_settled_events`

- [ ] **Step 3: Rewrite the cron's publish half**

Replace `_publish_event_row` and the body of `publish_settled_events` with:

```python
    async def _process_one(self, event: ClaimedEvent) -> bool:
        """Returns True on success. Never raises: one poisoned row must not
        stop the batch, and the queue records the failure for the retry."""
        try:
            await self._processor.process(event)
        except Exception as e:
            logger.warning(
                "event_processing_failed",
                event_id=event.id,
                event_type=event.event_type,
                source_id=event.source_id,
                error=str(e),
            )
            await self._queue.mark_failed(event.id, str(e))
            return False
        # Stamp the claimed row's own last_touch_at, never an app-clock now():
        # an edit landing between claim and completion would otherwise be older
        # than the stamp, fail `last_touch_at > completed_at`, and never re-queue.
        await self._queue.mark_done(event.id, event.last_touch_at)
        return True

    async def process_settled_events(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._window_hours)
        events = await self._queue.claim_batch(limit=self._batch_size, cutoff=cutoff)
        succeeded = 0
        for event in events:
            if await self._process_one(event):
                succeeded += 1
        if events:
            logger.info("settled_events_processed", claimed=len(events), succeeded=succeeded)
        return succeeded
```

Rewrite `publish_org_now` as `process_org_now`, keeping its existing
`on_progress` contract and `FORCE_PUBLISH_MAX_ROWS` cap, but calling
`claim_batch(limit=..., cutoff=None, org_id=org_id)` and `_process_one`. Progress
now reports rows actually ingested rather than rows queued — the job service
already tolerates long runs.

Leave `reconcile` unchanged.

- [ ] **Step 4: Rewire main.py**

Delete the `import boto3` line, the `sqs_client = boto3.client(...)` line, the
`SqsConsumer` construction, `_consumer`, `_consumer_task` and the
`asyncio.create_task(_consumer.run())`. Change the guard from
`if settings.sync.enabled and settings.sync.sqs_queue_url:` to
`if settings.sync.enabled:`, and its `else` branch to log
`brain_sync_disabled reason="sync.enabled=False"`. Construct:

```python
        queue = EventQueue(
            supabase_client,
            lease_seconds=settings.sync.claim_lease_seconds,
            max_attempts=settings.sync.claim_max_attempts,
        )
        processor = EventProcessor(
            event_router=event_router,
            ingestion_repo=ingestion_repo,
            tombstone=tombstone,
        )
        cron = BrainSyncCron(
            supabase=supabase_client,
            queue=queue,
            processor=processor,
            settledness_window_hours=settings.sync.settledness_window_hours,
            batch_size=settings.sync.claim_batch_size,
        )
```

and change the publisher job to:

```python
        _scheduler.add_job(
            cron.process_settled_events,
            trigger=IntervalTrigger(seconds=settings.sync.poll_interval_seconds),
            id="brain_sync_publisher",
            max_instances=1,
            coalesce=True,
        )
```

Also update the startup log to `logger.info("brain_sync_started", poll_seconds=settings.sync.poll_interval_seconds)` — there is no queue URL to report.

- [ ] **Step 5: Update the cron unit tests**

In `tests/unit/test_brain_sync_cron.py`, replace the `sqs_client` mock with a
fake exposing `claim_batch`, `mark_done`, `mark_failed`, and a fake processor
with `process`. Rename the tests that say "publish" to "process". Keep the
`cortex_events_for_org_unpublished` RPC test — `reconcile` still uses it.

- [ ] **Step 6: Run the whole cortex-backend suite**

Run: `docker compose exec -T cortex-backend python -m pytest tests/unit -v`
Expected: PASS, ~440 tests. Then the integration file:
`docker compose exec -T cortex-backend python -m pytest tests/integration -v -m integration`
Expected: PASS, 2 tests.

- [ ] **Step 7: Sweep the references Task 3 had to leave behind**

Task 3's byte-identical constraint meant it could not touch prose inside the
file it ported, and its verification grep only covered `src`. Four things
survive, all confirmed present:

1. `cortex-backend/scripts/_e2e_drain.py` and `_e2e_drain_parallel.py` still
   `import src.sync.sqs_consumer` and are broken. They are `boto3.client('sqs')`
   poll loops whose reason to exist disappears with the queue — **delete both.**
   `clear_and_reingest.py` imports only `src.main` and stays.
2. `event_processor.py`'s class docstring still opens "Long-running consumer for
   the cortex-ingestion-events.fifo queue. For each message: decode → …". Every
   clause describes deleted code. Rewrite it for the claim/process model.
3. `IngestionFailure`'s docstring still says "Lets SQS retry." It is now
   `mark_failed` plus lease expiry that retries — say that.
4. `cortex-backend/docs/cortex-v2-design.md:1074` still lists
   `sqs_consumer.py  # Async poll loop: SQS → route to handlers` in its layout
   tree. Update the filename and the description.

Rename the test `test_handle_failure_raises_for_sqs_retry` to match (3).

- [ ] **Step 8: Verify boto3 and SQS are gone from cortex-backend**

Run: `grep -rniE "boto3|sqs" cortex-backend --include='*.py' --include='*.md' | grep -v '\.pyc'`

Note this greps **all of `cortex-backend`**, not just `src` — scoping it to `src`
is what let the broken scripts and stale docs survive in the first place.
Expected: no output.

- [ ] **Step 9: Rebuild and prove the graph populates**

```bash
docker compose up -d --build cortex-backend
docker compose logs cortex-backend | grep brain_sync
```

Expected: `brain_sync_started poll_seconds=60` — **not** `brain_sync_disabled`.

Then confirm nodes appear:

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p "$(grep '^NEO4J_PASSWORD=' .env | cut -d= -f2-)" \
  --format plain "MATCH (n) RETURN count(n) AS total_nodes;"
```

Expected: greater than 0. If it is 0, check `cortex_events` actually has rows
past the 48h window — an empty ledger is not the same failure as a broken
consumer, and the two must not be confused.

- [ ] **Step 10: Commit**

```bash
git add cortex-backend/ && git commit -m "feat(cortex): ingest from Postgres instead of SQS

The producer and consumer both came across in the fork; the queue between them
did not, so startup logged brain_sync_disabled and Neo4j held zero nodes. Both
halves live in one container, so the queue was carrying rows out of Postgres
and back into the same process.

BrainSyncCron now claims a leased batch and processes it inline. publish_* is
renamed process_* because nothing is published any more. Force-publish progress
changes meaning from rows queued to rows actually in the graph."
```

---

### Task 5: Delete calendar intelligence

**Files:**
- Delete: `backend/app/services/calendar_intelligence_handler.py`, `calendar_intelligence_service.py`, `google_calendar_service.py`, `recall_calendar_service.py`, `intake_call_service.py`
- Delete: `backend/app/workers/calendar_intelligence_worker.py`
- Delete: `backend/app/api/v2/routers/internal_calendar_intelligence.py`, `integrations_gcal.py`
- Delete: `backend/tests/api/v2/test_internal_calendar_intelligence.py`, `test_integrations_gcal.py`, `test_webhooks_calendar.py`; `backend/tests/services/test_calendar_intelligence_service_import.py`, `test_google_calendar_retry.py`, `test_google_calendar_service.py`, `test_recall_calendar_retry.py`, `test_recall_calendar_service.py`; `backend/tests/workers/test_calendar_intelligence_resilience.py`, `test_calendar_intelligence_worker.py`
- Modify: `backend/app/api/v2/__init__.py`, `backend/app/main.py`, `backend/app/config.py`, `backend/app/api/v2/routers/webhooks.py`, `.env.example`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. This is subtractive.

**The one route that disappears.** `intake_call_service.py` backs
`POST /api/v2/admin/requisitions/{req_id}/intake-call`, which puts an
intake-call invite on a Google Calendar. It is already dead —
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` are blank, so no calendar can be
connected and it always raises `"Google Calendar not connected"`. It is
unrelated to `/api/v2/intake/sessions`, the intake flow that is kept.

- [ ] **Step 1: Delete the files**

```bash
git rm backend/app/services/calendar_intelligence_handler.py \
       backend/app/services/calendar_intelligence_service.py \
       backend/app/services/google_calendar_service.py \
       backend/app/services/recall_calendar_service.py \
       backend/app/services/intake_call_service.py \
       backend/app/workers/calendar_intelligence_worker.py \
       backend/app/api/v2/routers/internal_calendar_intelligence.py \
       backend/app/api/v2/routers/integrations_gcal.py
git rm backend/tests/api/v2/test_internal_calendar_intelligence.py \
       backend/tests/api/v2/test_integrations_gcal.py \
       backend/tests/api/v2/test_webhooks_calendar.py \
       backend/tests/services/test_calendar_intelligence_service_import.py \
       backend/tests/services/test_google_calendar_retry.py \
       backend/tests/services/test_google_calendar_service.py \
       backend/tests/services/test_recall_calendar_retry.py \
       backend/tests/services/test_recall_calendar_service.py \
       backend/tests/workers/test_calendar_intelligence_resilience.py \
       backend/tests/workers/test_calendar_intelligence_worker.py
```

- [ ] **Step 2: Remove the references**

- `backend/app/api/v2/__init__.py`: drop the `internal_calendar_intelligence` and `integrations_gcal` imports and their `include_router` lines.
- `backend/app/main.py`: drop the `run_calendar_intelligence_loops()` and `run_deferred_backfill()` tasks and their log lines.
- `backend/app/config.py`: delete `CALENDAR_INTELLIGENCE_ENABLED` and every `GOOGLE_*` setting.
- `backend/app/api/v2/routers/webhooks.py:129-133`: delete the `enqueue_calendar_sync_hint` import and call. Its enclosing handler is the Google Calendar push webhook; if the whole route exists only for that, delete the route too.
- Delete the intake-call route from `backend/app/api/v2/routers/admin/requisitions.py` and its `intake_call_service` import.
- `.env.example`: remove `GOOGLE_*` and any `CALENDAR_*` entries.

- [ ] **Step 3: Find anything left behind**

Run: `grep -rniE "calendar|gcal" backend/app | grep -v '\.pyc'`
Expected: no output. Any hit is a live reference that must be removed — a stale
import will fail at startup, not at test time.

- [ ] **Step 4: Run the full backend suite**

Run: `make test`
Expected: PASS. The count drops from 2909 by however many the ten deleted files
held; no *failures*. A failure here means something outside calendar depended on
it — investigate rather than delete the failing test.

- [ ] **Step 5: Rebuild and confirm the app still boots**

```bash
docker compose up -d --build backend && sleep 15 && curl -s localhost:8004/health
```
Expected: `{"status":"healthy","service":"backend"}`

- [ ] **Step 6: Commit**

```bash
git add -A backend/ .env.example
git commit -m "refactor: delete calendar intelligence

Unwanted for the self-hosted product and never usable here: GOOGLE_CLIENT_ID
and GOOGLE_CLIENT_SECRET were blank, so no calendar could be connected.

Takes intake_call_service with it, which removes
POST /requisitions/{id}/intake-call. That endpoint put an invite on a connected
calendar and therefore always raised 'Google Calendar not connected'. The
intake flow at /api/v2/intake/sessions is unaffected. Meeting capture is
unaffected: it runs through recall_service and the Recall webhook handlers."
```

---

### Task 6: Delete the Slack assistant

**Files:**
- Delete: `backend/app/api/v2/routers/integrations_slack.py`, `internal_slack_agent.py`, `internal_slack_integrations.py`, `webhooks_slack.py`
- Delete: `backend/app/services/slack_service.py`, `slack_blocks.py`, `slack_token_refresh.py`, `sqs_publisher.py`
- Delete: `backend/tests/api/v2/test_integrations_slack.py`, `test_internal_slack_agent.py`, `test_internal_slack_agent_endpoints.py`, `test_internal_slack_integrations_router.py`, `test_webhooks_slack.py`, `test_webhooks_slack_helpers.py`; `backend/tests/services/test_slack_service.py`; `backend/tests/services/test_s3_sqs_extra.py`
- Modify: `backend/app/api/v2/__init__.py`, `backend/app/main.py`, `backend/app/config.py`, `backend/app/api/v2/routers/webhooks_feedback.py:7,51-54`, `backend/app/services/requisition_service.py:284-294`, `backend/tests/services/test_requisition_service.py:536-560`, `backend/tests/api/v2/test_webhooks_feedback.py`, `.env.example`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. Subtractive.

**Why `sqs_publisher` goes too.** Its only two events, `feedback_complete` and
`intake_complete`, existed to wake the Slack assistant's parked workflow tasks.
The consumer was `mazle-assistant/src/services/sqs_consumer.py`, which was never
forked. With the assistant gone the publisher has no audience.

- [ ] **Step 1: Delete the files**

```bash
git rm backend/app/api/v2/routers/integrations_slack.py \
       backend/app/api/v2/routers/internal_slack_agent.py \
       backend/app/api/v2/routers/internal_slack_integrations.py \
       backend/app/api/v2/routers/webhooks_slack.py \
       backend/app/services/slack_service.py \
       backend/app/services/slack_blocks.py \
       backend/app/services/slack_token_refresh.py \
       backend/app/services/sqs_publisher.py
git rm backend/tests/api/v2/test_integrations_slack.py \
       backend/tests/api/v2/test_internal_slack_agent.py \
       backend/tests/api/v2/test_internal_slack_agent_endpoints.py \
       backend/tests/api/v2/test_internal_slack_integrations_router.py \
       backend/tests/api/v2/test_webhooks_slack.py \
       backend/tests/api/v2/test_webhooks_slack_helpers.py \
       backend/tests/services/test_slack_service.py \
       backend/tests/services/test_s3_sqs_extra.py
```

- [ ] **Step 2: Remove the publish_event call sites**

In `backend/app/api/v2/routers/webhooks_feedback.py`, delete the
`from app.services.sqs_publisher import publish_event` import and the whole
block that resolves `org_id` purely to publish:

```python
        supabase = get_supabase_admin_client()
        cr_result = await supabase.table("candidate_rounds") \
            .select("id, candidates!inner(requisition_id, requisitions!inner(organization_id))") \
            .eq("id", request.candidate_round_id) \
            .single() \
            .execute_async()
        if cr_result.data:
            org_id = cr_result.data.get("candidates", {}).get("requisitions", {}).get("organization_id")
            if org_id:
                await publish_event("feedback_complete", {...})
```

The `return {"success": True, ...}` immediately after it stays. Check whether
`get_supabase_admin_client` is still used elsewhere in that file before removing
its import.

In `backend/app/services/requisition_service.py`, delete the whole
`if new_status == "planned":` block containing the deferred import and
`publish_event("intake_complete", ...)`, including its `except Exception: pass`.

- [ ] **Step 3: Remove the references**

- `backend/app/api/v2/__init__.py`: drop the four Slack router imports and `include_router` lines.
- `backend/app/main.py`: drop the `run_slack_token_refresh_loop()` task and its log line.
- `backend/app/config.py`: delete every `SLACK_*` setting.
- `.env.example`: remove `SLACK_*`.
- `backend/tests/services/test_requisition_service.py:536-560`: delete the two tests that monkeypatch `sqs_publisher.publish_event`.
- `backend/tests/api/v2/test_webhooks_feedback.py`: its docstring names the SQS event; remove that test case and fix the docstring.

- [ ] **Step 4: Find anything left behind**

Run: `grep -rniE "slack|sqs" backend/app | grep -v '\.pyc'`
Expected: no output.

- [ ] **Step 5: Run the full backend suite**

Run: `make test`
Expected: PASS.

- [ ] **Step 6: Confirm boto3 is now only used by S3**

Run: `grep -rn "boto3" backend/app | grep -v '\.pyc'`
Expected: only `s3_service.py` and the Lambda invoker paths. SQS is gone.

- [ ] **Step 7: Commit**

```bash
git add -A backend/ .env.example
git commit -m "refactor: delete the Slack assistant integration

Not wanted for the self-hosted product, and the agent it talked to was never
forked - SLACK_AGENT_URL resolved to a service that does not exist in this
compose file.

sqs_publisher goes with it. Its only two events, feedback_complete and
intake_complete, existed to wake the assistant's parked workflow tasks, and
their consumer lived in the app that was left behind. With SQS_QUEUE_URL blank
both were already silent no-ops."
```

---

### Task 7: Feature defaults and truthful docs

**Files:**
- Modify: `backend/app/config.py:164` (`VOICE_ENABLED`), `:243` (`ATS_INTEGRATIONS_ENABLED`)
- Modify: `.env`, `.env.example` (drop the `RUN_BACKGROUND_WORKERS` override)
- Modify: `docs/architecture.md:127-140`
- Test: `backend/tests/test_config_defaults.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

**The rule.** Gate on credentials where credentials exist; keep a boolean only
where there is a real choice. Double-gating — needing both a key and a separate
switch — is what made intake, voice and the graph all look broken while
correctly configured.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_config_defaults.py
"""Defaults are a product decision, so they get a test.

Every one of these was found switched off on a fully-configured instance, and
each cost real debugging time before anyone suspected a default.
"""
from app.config import Settings


def _defaults() -> Settings:
    return Settings(
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SECRET_KEY="sb_secret_test",
        SUPABASE_JWT_SECRET="test-secret",
    )


def test_voice_is_on_by_default():
    # Gates /start-voice on the feedback and screening portals. Voice ships as
    # two containers; DEEPGRAM_API_KEY and OPENAI_API_KEY already decide
    # whether it can actually work.
    assert _defaults().VOICE_ENABLED is True


def test_ats_integrations_are_on_by_default():
    # Credentials live per-organization in ats_connections, not in env, so
    # there is nothing to gate on. With no connection rows the loops idle.
    assert _defaults().ATS_INTEGRATIONS_ENABLED is True


def test_background_workers_run_by_default():
    # Was off because it dragged in Slack and calendar. With those deleted it
    # is just intake stale-lock cleanup, which is wanted.
    assert _defaults().RUN_BACKGROUND_WORKERS is True


def test_signup_is_not_invite_gated_and_debug_is_off():
    # These two are correctly False; asserted so a later sweep does not flip
    # them along with the rest.
    s = _defaults()
    assert s.SIGNUP_INVITE_ONLY is False
    assert s.DEBUG is False


def test_deleted_features_have_no_settings_left():
    fields = set(Settings.model_fields)
    assert not [f for f in fields if f.startswith(("SLACK_", "GOOGLE_"))]
    assert "CALENDAR_INTELLIGENCE_ENABLED" not in fields
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker build -f backend/Dockerfile.test -t openrecruiting-backend-test . && docker run --rm -e ENV=test -v "$(pwd)/backend:/app" -w /app openrecruiting-backend-test python -m pytest tests/test_config_defaults.py -v`
Expected: FAIL on `VOICE_ENABLED` and `ATS_INTEGRATIONS_ENABLED`.

- [ ] **Step 3: Flip the defaults**

In `backend/app/config.py`: `VOICE_ENABLED: bool = True` and
`ATS_INTEGRATIONS_ENABLED: bool = True`.

In `.env` and `.env.example`, delete the `RUN_BACKGROUND_WORKERS=false` line so
the `True` default applies. Leave the surrounding comment only if it is still
accurate after the deletions; the current one describes calendar polling and
should go.

- [ ] **Step 4: Run to verify it passes**

Run the same command as Step 2.
Expected: PASS, 5 tests.

- [ ] **Step 5: Correct the docs**

In `docs/architecture.md`, the degradation table: delete any calendar and Slack
rows, and fix the Cortex row. It currently reads:

```
| `OPENAI_API_KEY` | Graph ingestion off; cortex-backend still serves and reports healthy |
```

`OPENAI_API_KEY` was never why ingestion was off. Replace with:

```
| `OPENAI_API_KEY` | Embeddings unavailable, so graph ingestion degrades; cortex-backend still serves and reports healthy |
```

In the "Data" section, replace the sentence describing the graph as "written by
`cortex-backend`" with a description of how: `cortex_events` is a Postgres work
ledger that `cortex-backend` polls, claims in leased batches, and ingests into
Neo4j, recording each result in `cortex_ingestion_record`.

- [ ] **Step 6: Full verification**

```bash
make test
docker compose up -d --build
make verify
```
Expected: backend suite PASS; all published services `ok`.

- [ ] **Step 7: Confirm the debrand gate still passes**

```bash
git ls-files -z | xargs -0 grep -Iil 'mazle' | grep -vE '^(NOTICE|README\.md|\.github/workflows/gate\.yml)$'
git ls-files | grep -i 'mazle'
```
Expected: no output from either.

- [ ] **Step 8: Commit**

```bash
git add backend/app/config.py backend/tests/test_config_defaults.py .env.example docs/architecture.md
git commit -m "fix(config): turn shipped features on by default

Voice shipped as two containers with its API keys set and was still off,
because VOICE_ENABLED gated it a second time. ATS was off with no credential to
gate on - they live per-org in ats_connections - so the flag only hid the
feature. RUN_BACKGROUND_WORKERS was off because it was one switch over five
loops, two of them Slack and calendar; with those deleted it is just intake
stale-lock cleanup, which is wanted.

The rule going in: gate on credentials where credentials exist, keep a boolean
only where there is a real choice. Locked in with tests, because every one of
these cost real debugging time before anyone suspected a default.

Also corrects architecture.md, which blamed a missing OPENAI_API_KEY for graph
ingestion being off. That was never the reason."
```

---

## Self-Review

**Spec coverage.** Every section maps to a task: the decision and architecture →
Tasks 2–4; the schema change → Task 1; components and renames → Tasks 2–4;
error handling (transient, poison pill, duplicate, crash) → Task 1's claim
predicate and Task 4's `_process_one`, verified by Task 4 Step 1's parking test;
the known single-consumer ordering limitation → documented in the Task 1 SQL
comment and the `EventQueue` docstring; deletions → Tasks 5–6; the
`intake_call_service` coupling → Task 5; feature defaults → Task 7; docs →
Tasks 5, 6, 7; testing → each task's own steps; verification → Task 4 Step 8 and
Task 7 Step 6. Sequencing matches the spec's three commits.

**Placeholder scan.** No TBDs. Every code step carries real code. Two steps
deliberately defer to existing conventions rather than invent them — the
`processor_and_deps` fixture in Task 3 Step 2 and the integration fixtures in
Task 4 Step 1 — and both say explicitly to follow the file's existing style
instead of inventing one.

**Type consistency.** `ClaimedEvent` fields (`id`, `event_type`, `source_id`,
`org_id`, `last_touch_at`, `publish_count`) are defined in Task 2 and used
unchanged in Tasks 3 and 4. `claim_batch(limit, cutoff, org_id)` /
`mark_done(event_id)` / `mark_failed(event_id, error)` keep one signature
throughout. The RPC's returned columns in Task 1 match `ClaimedEvent` exactly.
`process_settled_events` / `process_org_now` are used consistently after the
rename in Task 4, including the `ingestion_controller.py` call sites.

**One gap found and fixed during review.** The parking test in Task 4 Step 1
originally called `process_settled_events(ignore_lease=True)`, a parameter the
Step 3 implementation does not accept — and a claimed row is lease-blocked for
300s, so the test could not have looped six times. Adding a production
parameter that exists only for tests would be the wrong fix. Task 4 Step 1 now
builds `cron_with_failing_handler` with `EventQueue(lease_seconds=0)` and calls
`process_settled_events()` with no arguments.
