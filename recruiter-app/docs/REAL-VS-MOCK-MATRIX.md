# Real vs Mock — Service Data-Source Matrix (FE-F5)

This document makes the data source of **every** `recruiter-app` service method
explicit, post-FE-F5. It is the source of truth for "is this screen showing
real backend data or fabricated demo data?" — a GA gate.

## How data routing works

`isV2ApiEnabled()` (`src/lib/env.ts`) defaults **TRUE**. It returns `false`
only when `NEXT_PUBLIC_V2_API=false` (the opt-out test/demo path).

- **v2 path (production, default):** services call the real backend
  `/api/v2/*` via `v2Client`.
- **mock path (tests/demo only):** services read an in-memory localStorage DB
  seeded from `src/fixtures/*` via `src/services/seed.ts` + `mock-db.ts`.

**FE-F5 fix:** the mock seed factory (`globalThis.__SEED`) is now
registered **only when `!isV2ApiEnabled()`** (`registerSeedFactory()` in
`seed.ts`, called once from `AppShell`). In production it is never registered,
so a service that still reads `getDb()` can no longer silently fabricate data.
Every method below that has no real endpoint now throws
`notImplementedInV2(...)` (`ServiceError` with code `not_found`, message
"This feature is not available yet.", `rawDetail` prefix
`NOT_IMPLEMENTED_IN_V2:`) on the v2 path instead of returning seed data.

## Legend

- **REAL (v2)** — hits a real `/api/v2/*` endpoint via `v2Client` when v2 is on.
- **NOT-AVAILABLE-IN-V2** — no backend endpoint yet; throws `notImplementedInV2`
  on the v2 path. Mock path still works for tests/demo.
- **MOCK-ONLY-TEST-PATH** — intentionally never wired to v2; only meaningful in
  the opt-out test/demo path. (Used by tests; not on any production screen, or
  the production screen reads it through a v2 sibling.)

## Matrix

### `billing.ts`
| Method | Source | Notes |
|---|---|---|
| `getOverview` | REAL (v2) | `GET /api/v2/billing/overview`. v2-only (no mock branch). Returns flat `BillingOverview`. |

### `team.ts`
| Method | Source | Notes |
|---|---|---|
| `get` | REAL (v2) | `GET /api/v2/team` |
| `invite` | REAL (v2) | `POST /api/v2/team/invite` |
| `cancelInvite` | REAL (v2) | `DELETE /api/v2/team/invites/{id}` |
| `acceptInvite` | REAL (v2) | `POST /api/v2/team/accept-invite` |
| `remove` | REAL (v2) | `DELETE /api/v2/team/members/{id}` |

### `requisitions.ts`
| Method | Source | Notes |
|---|---|---|
| `list` | REAL (v2) | `GET /api/v2/roles` (paginated, status, q) |
| `get` | REAL (v2) | `GET /api/v2/roles/{id}` + `/plan` (parallel) |
| `create` | **NOT-AVAILABLE-IN-V2** | No `POST /api/v2/roles` yet (TODO PR6). Throws `notImplementedInV2`. |
| `update` | MOCK-ONLY-TEST-PATH | No v2 endpoint; not gated (no production caller — intake edits go via `updateIntake`, which IS gated). Mock path only. |
| `setStatus` | REAL (v2) | `POST /api/v2/roles/{id}/close` or `/reopen`. `intake_pending` transition throws `invalid_state` (no v2 endpoint). |
| `updateIntake` | **NOT-AVAILABLE-IN-V2** | No v2 intake-notes endpoint. Throws `notImplementedInV2` (was silently delegating to mock `update`). |
| `getPlan` | REAL (v2) | `GET /api/v2/roles/{id}/plan` |
| `addRound` | REAL (v2) | `POST /api/v2/roles/{id}/plan/rounds` |
| `updateRound` | REAL (v2) | `PUT /api/v2/plan/rounds/{id}` |
| `deleteRound` | REAL (v2) | `DELETE /api/v2/plan/rounds/{id}` |
| `reorderRounds` | REAL (v2) | `POST /api/v2/roles/{id}/plan/rounds/reorder` (If-Match) |
| `addQuestion` | REAL (v2) | `POST /api/v2/plan/rounds/{id}/questions` |
| `updateQuestion` | REAL (v2) | `PUT /api/v2/plan/questions/{id}` |
| `deleteQuestion` | REAL (v2) | `DELETE /api/v2/plan/questions/{id}` |
| `attachScreeningAgent` | **NOT-AVAILABLE-IN-V2** | No v2 screening-agent endpoint. Throws `notImplementedInV2`. |
| `detachScreeningAgent` | MOCK-ONLY-TEST-PATH | No v2 endpoint; not in the FE-F5 audit set. Paired with attach (also not-available). Mock path only. |
| `updateScreeningQuestion` | MOCK-ONLY-TEST-PATH | No v2 endpoint; not in the FE-F5 audit set. Mock path only. |
| `saveSourcingStrategy` | **NOT-AVAILABLE-IN-V2** | No v2 endpoint. Throws `notImplementedInV2`. |
| `listSourcingStrategies` | **NOT-AVAILABLE-IN-V2** | No v2 endpoint. Throws `notImplementedInV2`. |

### `candidates.ts`
| Method | Source | Notes |
|---|---|---|
| `listForReq` | REAL (v2) | `GET /api/v2/roles/{id}/candidates` (pipeline RPC) |
| `get` | REAL (v2) | Derived from the pipeline RPC `GET /api/v2/roles/{id}/candidates`, filtered to the id (FE-F5: was mock-only). |
| `create` | REAL (v2) | `POST /api/v2/roles/{id}/candidates` |
| `update` | **NOT-AVAILABLE-IN-V2** | No v2 candidate PATCH. Throws `notImplementedInV2` (FE-F5). |
| `remove` | **NOT-AVAILABLE-IN-V2** | No v2 candidate DELETE. Throws `notImplementedInV2` (FE-F5). |
| `setStatus` | **NOT-AVAILABLE-IN-V2** | No v2 candidate status endpoint. Throws `notImplementedInV2` (FE-F5). |
| `listRounds` | REAL (v2) | Derived from the pipeline RPC |
| `addCustomRound` | REAL (v2) | `POST /api/v2/roles/{id}/candidates/{cid}/rounds` |
| `removeRoundForCandidate` | REAL (v2) | resolves cr via packet, `DELETE .../rounds/{crId}` |
| `getPacket` | REAL (v2) | `GET /api/v2/roles/{id}/candidates/{cid}/packet` |
| `getRound` | REAL (v2) | Derived from the packet RPC, matched on round id (FE-F5: was mock-only). |

### `interviews.ts`
| Method | Source | Notes |
|---|---|---|
| `schedule` | REAL (v2) | resolves cr, `POST /api/v2/candidate-rounds/{crId}/schedule` |
| `reschedule` | REAL (v2) | `PUT .../schedule` |
| `cancel` | REAL (v2) | `POST .../cancel` |
| `sendReminder` | **NOT-AVAILABLE-IN-V2** | No v2 reminder endpoint. Throws `notImplementedInV2` (FE-F5). |

### `feedback.ts`
| Method | Source | Notes |
|---|---|---|
| `getRoundFeedback` | REAL (v2) | Derived from the packet RPC `feedback_questions[].feedback_entries` (FE-F5: was mock-only). |
| `submitFeedback` | REAL (v2) | `POST /api/v2/candidate-rounds/{crId}/feedback` |
| `requestFeedback` | REAL (v2) | `POST .../request-feedback` |
| `getRecordingUrl` | REAL (v2) | `GET .../recording-url` |
| `getTranscript` | REAL (v2) | `GET .../transcript` |
| `reprocess` | REAL (v2) | `POST .../reprocess` |
| `getRecording` | REAL (v2) | composes recording-url + transcript |

### `debrief.ts`
| Method | Source | Notes |
|---|---|---|
| `get` | **NOT-AVAILABLE-IN-V2** | No v2 debrief endpoint. Throws `notImplementedInV2` (FE-F5). |
| `getInsights` | **NOT-AVAILABLE-IN-V2** | No v2 debrief endpoint. Throws `notImplementedInV2` (FE-F5). |

### `activity.ts`
| Method | Source | Notes |
|---|---|---|
| `list` | **NOT-AVAILABLE-IN-V2** | No v2 activity-feed endpoint. Throws `notImplementedInV2` (FE-F5). Local activity rows written by interview/feedback mutations are mock-path-only UX glue. |

### `profile.ts`
| Method | Source | Notes |
|---|---|---|
| `get` | **NOT-AVAILABLE-IN-V2** | No v2 profile endpoint. Throws `notImplementedInV2` (FE-F5). |
| `updateTimezone` | **NOT-AVAILABLE-IN-V2** | No v2 endpoint. Throws `notImplementedInV2` (FE-F5). |
| `updateName` | **NOT-AVAILABLE-IN-V2** | No v2 endpoint. Throws `notImplementedInV2` (FE-F5). |
| `getNotificationPrefs` | **NOT-AVAILABLE-IN-V2** | No v2 endpoint. Throws `notImplementedInV2` (FE-F5). |
| `updateNotificationPrefs` | **NOT-AVAILABLE-IN-V2** | No v2 endpoint. Throws `notImplementedInV2` (FE-F5). |

### `integrations.ts`
| Method | Source | Notes |
|---|---|---|
| `list` | **NOT-AVAILABLE-IN-V2** | No v2 integrations endpoint. Throws `notImplementedInV2` (FE-F5). |
| `connect` | **NOT-AVAILABLE-IN-V2** | No v2 endpoint. Throws `notImplementedInV2` (FE-F5). |
| `disconnect` | **NOT-AVAILABLE-IN-V2** | No v2 endpoint. Throws `notImplementedInV2` (FE-F5). |
| `getStatus` | **NOT-AVAILABLE-IN-V2** | No v2 endpoint. Throws `notImplementedInV2` (FE-F5). |

### `public-feedback.ts`
| Method | Source | Notes |
|---|---|---|
| (all) | REAL (v2) | No-login token portal; calls `/api/v2/public/feedback/*` directly. No mock branch. |

### `events.ts` / `latency.ts` / `mock-db.ts` / `seed.ts`
Infrastructure, not data services:
- `events.ts` — in-process named-event bus (refetch glue). Path-agnostic.
- `latency.ts` — `simulate()` artificial delay (mock path only).
- `mock-db.ts` / `seed.ts` — localStorage mock + fixtures. `registerSeedFactory()`
  is the FE-F5 gate (no-op when v2 enabled).

## Summary

- **REAL (v2):** billing (1), team (5), most of requisitions/candidates/
  interviews/feedback, public-feedback. Includes 3 methods promoted
  to real in FE-F5 (`candidates.get`, `candidates.getRound`,
  `feedback.getRoundFeedback`) by deriving from existing pipeline/packet RPCs.
- **NOT-AVAILABLE-IN-V2 (throws, no fabrication):** `requisitions.create`,
  `requisitions.updateIntake`, `requisitions.attachScreeningAgent`,
  `requisitions.saveSourcingStrategy`, `requisitions.listSourcingStrategies`,
  `candidates.update`, `candidates.remove`, `candidates.setStatus`,
  `interviews.sendReminder`, all of `debrief.*`,
  all of `activity.*`, all of `profile.*`, all of `integrations.*`.
- **MOCK-ONLY-TEST-PATH (not gated, no production caller):**
  `requisitions.update`, `requisitions.detachScreeningAgent`,
  `requisitions.updateScreeningQuestion`.

**GA implication:** any UI surface relying on a NOT-AVAILABLE-IN-V2 method
(Settings profile/notifications/integrations, dashboard Activity feed, Debrief
tab, candidate edit/delete/status, intake-note edit, role create, sourcing
strategies, screening-agent attach, interview reminders) will surface a
"not available yet" error rather than fabricated data. These need real backend
endpoints before those screens can ship as GA.
