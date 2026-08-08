# End-to-end checklist

What was verified before release, how, and — just as importantly — what was
**not**, so you know which parts are proven and which you are the first to try.

Verified on macOS (Apple Silicon), Docker Desktop 29.3.1.

The infrastructure and wiring rows below were first verified against a local
Supabase. The authenticated golden path was re-verified on **2026-08-07** against a
real cloud Supabase project, which closed most of what this document previously
listed as UNVERIFIED. What remains unproven is now limited to the legs that need a
live third-party call or dashboard configuration — see the table at the bottom.

## Infrastructure

| # | Check | Result |
|---|---|---|
| 1 | `docker compose config` parses | **PASS** |
| 2 | All 11 images build from a clean context | **PASS** |
| 3 | All 11 containers start | **PASS** |
| 4 | `backend` `/health` | **PASS** — `{"status":"healthy","service":"backend"}` |
| 5 | `landing` serves `/` and `/login` | **PASS** — 200 |
| 6 | `recruiter-app` redirects unauthenticated traffic | **PASS** — 307 → `localhost:3000/login?redirect=%2F` |
| 7 | `cortex-backend` `/api/v1/health` | **PASS** — reports `neo4j: up` |
| 8 | `cortex-mcp` `/health` | **PASS** — 200 |
| 9 | `neo4j` healthy + Cypher write/read/delete | **PASS** |
| 10 | `voice-agent` `/health` | **PASS** — `{"status":"ok"}` |
| 11 | `voice-frontend` serves `/<session-token>` | **PASS** — 200 (`/` correctly 404s; there is no root route) |
| 12 | 3 workers healthy and internal-only | **PASS** |

## Wiring

| # | Check | Result |
|---|---|---|
| 13 | `schema.sql` applies to an empty database, zero errors | **PASS** — under `ON_ERROR_STOP=1` |
| 14 | Schema matches the migration replay | **PASS** — 53 tables, 178 functions, 89 policies, 222 indexes, 25 triggers, 50 RLS tables |
| 15 | `seed.sql` applies on top and is idempotent | **PASS** — re-run leaves 3 candidate-rounds, not 6 |
| 16 | Backend dispatches to `intake-agent` over HTTP | **PASS** |
| 17 | Backend dispatches to `intake-context-builder` | **PASS** |
| 18 | Backend dispatches to `feedback-agent` | **PASS** |
| 19 | Unshipped `intake_transcript` target fails loudly | **PASS** — `UnknownJobTargetError` |
| 20 | Recall webhook routes mounted, unsigned request rejected | **PASS** — 401 |
| 21 | MCP JWKS points at the backend, not the retired port | **PASS** — `http://backend:8004/.well-known/jwks.json` |

## Identity and safety

| # | Check | Result |
|---|---|---|
| 22 | `RECALL_BOT_NAME` ∈ `BOT_SPEAKER_NAMES`, asserted at startup | **PASS** — verified at runtime |
| 23 | Backend and worker speaker sets identical | **PASS** |
| 24 | Voice agent and backend agree on `"Scout Interviewer"` | **PASS** |
| 25 | `SECURITY DEFINER` functions unreachable by `anon`/`authenticated` | **PASS** — 45 → 0, all 45 still callable by `service_role` |
| 26 | MCP rejects writes and forces `$org_id` from the token | **PASS** — regression tests |
| 27 | No brand references in contents or filenames | **PASS** — only NOTICE + README attribution |
| 28 | `gitleaks` across all commits | **PASS** — no leaks found |
| 29 | No captured interview data tracked or in history | **PASS** |

## Tests

All five suites re-run 2026-08-07.

| Suite | Command | Result |
|---|---|---|
| backend (pytest, Python 3.11) | `make test` | **2105 passed**, 5 skipped (2110 collected) |
| cortex-backend (pytest) | `make test-cortex` | **486 passed**, 2 deselected |
| recruiter-app (bun, directory slices) | see below | **1224 passed**, 0 failed |
| landing (vitest) | `npx vitest run` | **31 passed** |
| cortex-mcp (pytest) | `python -m pytest -q` | **152 passed**, 8 skipped |

Never run a bare `bun test` in `recruiter-app` — the full suite is known to hang.
Run directory slices. The nine that cover every unit test file:

```
src/services  src/stores  src/hooks  src/lib  src/domain
src/components  src/app  src/types  src/fixtures
```

`src/test/e2e` is deliberately excluded: those specs need live infrastructure, and
`tsconfig.json` excludes the directory too.

### Typecheck

`npx tsc --noEmit` in `recruiter-app` reports **46 errors, all of them in test
files** — 0 in shipped code. No app sets `ignoreBuildErrors`, so `next build`
typechecks the production graph and passes. The test-file errors are real debt but
gate nothing.

## The golden path

Verified 2026-08-07 against a real cloud Supabase project, by driving the HTTP API
directly with a real user's access token.

| # | Step | Result |
|---|---|---|
| 30 | Password sign-in against Supabase | **PASS** — returns an access token |
| 31 | `/api/v2/auth/me` accepts that token | **PASS** — 200 with `organization_id` and `is_staff` |
| 32 | Requisitions readable for the org | **PASS** — 6 rows for the demo org |
| 33 | Staff admin API reachable | **PASS** — `/api/v2/admin/organizations` returns 5 |
| 34 | AI intake session creation | **PASS** — 201 in ~1.1s; dispatch is fire-and-forget, so the response no longer waits on the worker |
| 35 | Graph prefill runs | **PASS** — `intake-context-builder` invoked, session reaches `status: ready` with 9 answer slots |
| 36 | Live LLM intake conversation | **PASS** — `POST /text/opening` streams a real response in ~3.2s |

Sign-in is `signInWithPassword`; there is no self-serve signup (`/signup` redirects
to `/login`). Create users through the Supabase Auth admin API.

## Still unverified

| # | Step | Status |
|---|---|---|
| 37 | Capture a live interview via Recall | **UNVERIFIED** — needs a key plus a tunnel reachable from Recall |
| 38 | AI feedback appears on a completed round | **UNVERIFIED** — depends on 37 |
| 39 | Google OAuth sign-in | **UNVERIFIED** — the code is complete; the Supabase dashboard provider is not configured |

`WEBHOOK_BASE_URL` must point at a live tunnel for 37. If it is an ngrok free URL it
changes on every ngrok restart, which is the first thing to check when webhooks go
quiet.

If the browser leg lands you back on the login page, check the Supabase redirect URL
allow-list (`docs/setup/supabase.md` step 4) before anything else.

## Reproducing

```bash
git clone <repo> && cd OpenRecruiting
cp .env.example .env
# fill SUPABASE_URL, SUPABASE_SECRET_KEY, SUPABASE_JWT_SECRET,
# NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
# then run schema.sql (and optionally seed.sql) per docs/setup/supabase.md
docker compose up -d --build
make verify
```

`make verify` prints one line per service. `voice-agent` reporting DOWN without
`OPENAI_API_KEY` and `DEEPGRAM_API_KEY` is expected.
