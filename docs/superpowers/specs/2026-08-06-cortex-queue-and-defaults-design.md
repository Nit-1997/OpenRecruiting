# Cortex ingestion without SQS, and honest feature defaults

Status: approved, not yet implemented
Date: 2026-08-06

## Problem

Three faults share one shape: machinery that was kept, wired to something that
was not, with a blank config value making the failure silent.

**Cortex ingestion is dead.** The knowledge graph is a headline feature in the
README. Its producer (`BrainSyncCron`) and consumer (`SqsConsumer`) both came
across in the fork, but the SQS queue between them did not. Startup logs
`brain_sync_disabled reason=no sqs_queue_url` and moves on. Neo4j holds **0
nodes**, verified directly. This is why intake prefill returns a nine-question
scaffold with no substance — the context-builder queries Cortex, and Cortex has
nothing.

**The docs assert the opposite.** `docs/architecture.md` describes the graph as
"written by cortex-backend", and its degradation table blames a missing
`OPENAI_API_KEY` for ingestion being off. That key is set. SQS is not mentioned
anywhere in the docs or `.env.example`.

**Features are double-gated.** Several need both credentials *and* a separate
boolean, so holding the key is not enough to turn the feature on. Voice is off
despite shipping two containers. `RUN_BACKGROUND_WORKERS` is off because it is a
single switch over five unrelated loops, two of which are unwanted — the cost
being that intake stale-lock cleanup never runs.

## Goals

- Cortex ingestion works after `docker compose up`, with no AWS account.
- Defaults are enabled. A feature is gated by whether its credentials exist, not
  by a second boolean that also has to be found and flipped.
- Slack assistant and calendar intelligence are gone, not merely disabled.
- The docs describe what the code does.

## Non-goals

- No general-purpose message broker. See "Decision".
- No multi-replica `cortex-backend`. Single-consumer ordering is assumed and
  documented, not engineered around.
- Recall meeting capture, the voice agent, and the intake flow are untouched.

## Decision: no broker

`cortex_events` is already a durable Postgres ledger carrying `published_at`,
`publish_count` and `last_error`. SQS was only moving rows out of Postgres and
into a consumer **in the same container**. A broker between two halves of one
process earns nothing.

Rejected, with reasons worth recording:

- **NATS JetStream** — the right choice *if* a broker were wanted. Apache-2.0
  (matching this repo), ~20MB, and it maps cleanly onto the semantics in use:
  subject = message group, `Nats-Msg-Id` = dedup ID, `ack_wait` = visibility
  timeout. Rejected only because there is exactly one producer/consumer pair and
  they share a process. Revisit if a second queue user appears.
- **Valkey / Redis Streams** — familiar, but no native dedup, so the
  `MessageDeduplicationId` window becomes our code. Note for the future: Redis
  itself is no longer OSI-open-source (RSALv2/SSPL since 2024); an Apache-2.0
  project should ship Valkey.
- **ElasticMQ** — a true drop-in, needing only `endpoint_url`. Rejected because
  this must be the shipped self-host default, and an SQS emulator is a dev-test
  tool.

## Architecture

Before:

```
cortex_events → BrainSyncCron.publish_settled_events → SQS ⇢ (never configured)
                SqsConsumer.run ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
                  → handle_message → event_router → Neo4j → cortex_ingestion_record
```

After — delete the middle, keep both ends:

```
cortex_events → EventQueue.claim_batch()   (SELECT … FOR UPDATE SKIP LOCKED)
              → EventProcessor.process(row) → event_router → Neo4j
                                            → cortex_ingestion_record
```

### Semantics mapping

| SQS concept | Postgres equivalent | Already present |
|---|---|---|
| `MessageGroupId` FIFO | `ORDER BY last_touch_at`, single consumer | n/a |
| `MessageDeduplicationId` | primary key + the `last_touch_at >= incoming` guard | yes |
| `VisibilityTimeout` | `published_at` as claim lease; expired ⇒ re-claimable | yes |
| retry count / DLQ | `publish_count`, `last_error` | yes |
| long polling | fixed-interval poll | n/a |

`published_at` changes meaning from "handed to SQS" to "claimed at". A row is
eligible when it is past the 48h settledness window **and** unclaimed, or its
claim lease has expired.

### Schema change

Corrected during planning; the first draft of this spec claimed no migration was
needed. Two things are required, both small:

1. **One new column** — `cortex_events.completed_at timestamptz NULL`.
   Completion is currently recorded only in `cortex_ingestion_record`, a
   different table, so `cortex_events` alone cannot distinguish "claimed and
   finished" from "claimed and then crashed". The existing predicate
   (`published_at IS NULL OR last_touch_at > published_at`) makes a crashed
   claim look permanently done, leaving the **weekly** reconcile as the only
   recovery. With `completed_at`, an expired lease recovers it in minutes.
2. **One new RPC** — `cortex_events_claim_batch(...)`. cortex-backend talks to
   Postgres only through the Supabase REST client (there is no asyncpg or
   psycopg dependency), so `FOR UPDATE SKIP LOCKED` cannot be expressed from
   Python. It goes in a `SECURITY DEFINER` function, following the existing
   `cortex_events_settled` and `cortex_events_for_org_unpublished` precedent.

No columns are dropped and no data is rewritten, so the change is additive and
safe to apply to a live database.

## Components

| File | Change |
|---|---|
| `sync/event_queue.py` | **New.** `claim_batch()`, `mark_done()`, `mark_failed()`. Pure Postgres, no domain knowledge. ~120 lines. |
| `sync/sqs_consumer.py` → `sync/event_processor.py` | Rewritten header, unchanged body. Drop the six JSON-decode lines and the `run()` poll loop; `process(event)` takes a `cortex_events` row. Repo lookup, staleness guard, tombstone, router call and `IngestionRecord` upsert are untouched. |
| `sync/brain_sync_cron.py` | Claims and processes inline instead of calling `send_message`. Constructor loses `sqs_client` and `queue_url`. |
| `main.py` | Delete the boto3 client, the `SqsConsumer` task, and the `sqs_queue_url` guard. Sync is then gated on `sync.enabled` alone. |
| `config/settings.py` | Remove `sync.sqs_queue_url` and `sync.aws_region`; retune as below. |

### Tuning

The two loops collapse into one, so the settings follow:

| Setting | Now | After | Reason |
|---|---|---|---|
| `publisher_interval_hours` | `24` | `poll_interval_seconds: 60` | Eligibility is gated by the 48h settledness window, not the poll rate. Polling every 60s lets newly-settled rows and force-publish runs land promptly without hammering Postgres. A 24h loop would leave a settled row waiting up to another day. |
| `consumer_visibility_timeout` | `300` | `claim_lease_seconds: 300` | Same value, renamed. A claim older than this is treated as abandoned and re-claimable. |
| `consumer_max_messages` | `10` | `claim_batch_size: 10` | Same value, renamed. |
| `consumer_wait_seconds` | `20` | removed | Long-poll parameter with no meaning against Postgres. |
| `settledness_window_hours`, `publish_batch_size` | — | unchanged | Still gate eligibility and the force-publish cap. |

### Renames

`publish_settled_events` → `process_settled_events`, `publish_org_now` →
`process_org_now`. Three call sites. Once nothing is published, "publish" is a
lie, and a name that outlives its meaning is the exact failure mode this work
exists to clear up — `RECRUITER_PORTAL_URL`, and `enqueue_calendar_sync_hint`'s
`RuntimeError("sqs down")` for a Postgres write.

### Behaviour change requiring sign-off

Force-publish becomes honest but slower. Today `publish_org_now` returns once
rows reach SQS, so its progress means "queued" and the job can report success
while ingestion later fails unseen. Inline processing makes progress mean
"actually in Neo4j". `cortex_force_publish_jobs` already handles long async jobs
with progress reporting and 5-minute stuck detection, so this fits — but the
call now does real work.

## Error handling

Strictly better than today, because nothing in the repo configures an SQS DLQ.

- **Transient failure** — `last_error` set, `published_at` left at the claim
  time; re-claimed once the lease expires.
- **Poison pill** — `publish_count` increments per claim. Past `max_attempts`
  (default 5) the row is *parked*: skipped by the claimer, `last_error`
  retained, logged once. Today an undeliverable message would redeliver forever.
- **Duplicate or stale** — the existing `last_touch_at >= incoming` guard.
- **Crash mid-process** — the lease expires and the row returns. Equivalent to a
  missed SQS delete.

### Known limitation

Strict per-entity ordering holds because there is a single `cortex-backend`.
With replicas, `SKIP LOCKED` could hand two edits to one entity to two workers
concurrently. The `last_touch_at >= incoming` guard makes that *safe* — the
stale edit is skipped, not misapplied — but not *ordered*. This will be stated
in a code comment rather than papered over. The fix, if replicas ever happen, is
to claim per `event_type:source_id` group.

## Deletions

31 files, ~14,700 lines.

- **Calendar** — `calendar_intelligence_{handler,service,worker}.py`,
  `internal_calendar_intelligence.py`, `google_calendar_service.py`,
  `recall_calendar_service.py`, `integrations_gcal.py`
- **Slack** — `integrations_slack.py`, `internal_slack_{agent,integrations}.py`,
  `webhooks_slack.py`, `slack_{service,blocks,token_refresh}.py`
- **Orphaned by the above** — `sqs_publisher.py`. Its two events
  (`feedback_complete`, `intake_complete`) existed only to wake the Slack
  assistant, which was never forked.
- 17 test files, the `SLACK_*` / `GOOGLE_*` / `CALENDAR_*` settings, both
  lifespan loops, and the matching `.env.example` entries.

### Coupling to resolve

`intake_call_service.py` imports `google_calendar_service` and backs
`POST /requisitions/{id}/intake-call`, which puts an intake-call invite on a
calendar. It is **already dead**: `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`
are blank, so no calendar can be connected and the call always raises
`"Google Calendar not connected"`. It is unrelated to the intake flow at
`/api/v2/intake/sessions`, which needs no calendar. It is deleted with the rest —
noted because a route disappears, not just internals.

`recall_calendar_service` is used only by `google_calendar_service` and leaves
with it. Meeting capture is untouched: that path runs through `recall_service`
and the Recall webhook handlers, which stay.

## Feature defaults

The rule: **gate on credentials where credentials exist; keep a boolean only
where there is a real choice.**

| Setting | Now | After | Reason |
|---|---|---|---|
| `VOICE_ENABLED` | `False` | `True` | Gates `/start-voice` on the feedback and screening portals. Voice ships as two containers, and `DEEPGRAM_API_KEY` / `OPENAI_API_KEY` already decide whether it can work. |
| `RUN_BACKGROUND_WORKERS` | `.env` `false` | remove the override (default is already `True`) | It was off because it dragged in Slack and calendar. With those gone it is just intake stale-lock cleanup, which is wanted and currently never runs. |
| `ATS_INTEGRATIONS_ENABLED` | `False` | `True`, flag kept | ATS credentials live per-organization in `ats_connections`, not in env, so there is no credential to gate on — the flag is a genuine switch over background loops. With no connection rows the loops idle harmlessly, so "nothing configured" should mean "does nothing", not "switched off". |
| `CALENDAR_INTELLIGENCE_ENABLED` | `False` | deleted with the feature | — |
| `sync.enabled` (cortex) | `True` | unchanged; the `sqs_queue_url` guard goes | Then it actually runs. |
| `SIGNUP_INVITE_ONLY`, `DEBUG` | `False` | unchanged | Correct already. Open signup and no debug are right defaults, not oversights. |

## Documentation

- `docs/architecture.md` — drop the calendar and Slack rows from the degradation
  table; correct the Cortex row, which blames `OPENAI_API_KEY` for something it
  never caused. Describe ingestion as Postgres-polled.
- `.env.example` — remove `SLACK_*`, `GOOGLE_*`, `CALENDAR_*`. Nothing is added:
  the queue needs no new variable, and the tuning settings above are
  cortex-backend defaults in `settings.py` that only need an entry if an
  operator wants to override them.
- `README.md` — container count and service table if the count changes (it does
  not; no container is added or removed).

## Testing

Against ~440 existing cortex-backend tests and 2,909 backend tests.

- `test_sqs_consumer.py` (133 lines) → `test_event_processor.py`. Swap the
  message-shaped fixture for a row-shaped one; assertions are unchanged because
  the logic is.
- `test_brain_sync_cron.py` (238 lines) — replace the `sqs_client` mock with an
  `EventQueue` fake.
- **New** `test_event_queue.py` — eligibility window, lease expiry, max-attempts
  parking, and a real two-connection `SKIP LOCKED` test, so the concurrency
  claim is proven rather than asserted.
- **New** integration test — seed `cortex_events`, run one pass, assert Neo4j
  nodes and a `cortex_ingestion_record` row. This is the test that would have
  caught the current 0-node state.
- Deleting Slack and calendar removes 17 test files; the remaining suites must
  stay green, which is the check that nothing else depended on them.

## Sequencing

Three separable commits, in this order:

1. **Queue swap** — the change needing real verification. Ends with Neo4j
   holding nodes.
2. **Deletions** — the large reviewable diff. Mechanical once (1) is proven.
3. **Flag defaults and docs** — small, and easiest to review after the dead
   features are gone.

## Verification

Done means all of:

- `docker compose up` on a clean checkout, and `cortex_events` rows drain
  without any queue configuration.
- Neo4j node count is greater than zero after a seeded ingestion run.
- A row failed five times is parked, not retried forever.
- Intake prefill returns real graph-derived context rather than an empty
  scaffold — the user-visible proof that ingestion works.
- Backend and cortex-backend suites green.
- `make verify` green on all published services.

## Risks

- **The deletion is large** (~14,700 lines) and could remove something with a
  non-obvious caller. Mitigated by running the full suites after, and by
  deleting *after* the queue change is proven so failures are attributable.
- **The 48h settledness window means nothing ingests immediately.** Testing will
  need either seeded rows with an old `last_touch_at` or a temporarily shortened
  window. Worth an explicit note in the plan so it is not mistaken for a bug.
