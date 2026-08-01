# End-to-end checklist

What was verified before release, how, and — just as importantly — what was
**not**, so you know which parts are proven and which you are the first to try.

Verified on macOS (Apple Silicon), Docker Desktop 29.3.1, against a local
Supabase for the schema work. No cloud Supabase project was available in the
build environment, so anything requiring a real sign-in is marked **UNVERIFIED**
rather than assumed.

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

| Suite | Result |
|---|---|
| backend (pytest, Python 3.11) | **2908 passed**, 5 skipped |
| recruiter-app (bun, directory slices) | **1269 passed** |
| landing (vitest) | **31 passed** |
| cortex-mcp (pytest) | **152 passed**, 8 skipped |

Never run a bare `bun test` in `recruiter-app` — the full suite is known to hang.
Run directory slices, as `docs/` and the CI config do.

## UNVERIFIED — needs a cloud Supabase project

These are the steps a first-time user should expect to shake out. Everything they
depend on is verified above; what is unproven is the round trip through a real
Supabase project.

| # | Step | Status |
|---|---|---|
| 30 | Sign up / sign in on landing | **UNVERIFIED** |
| 31 | Cookie handoff lands you authenticated in the dashboard | **UNVERIFIED** — the redirect leg is verified; the authenticated leg is not |
| 32 | Create a requisition and see `source = native` | **UNVERIFIED** — the schema default and CHECK are verified |
| 33 | Run AI intake end to end (needs `ANTHROPIC_API_KEY`) | **UNVERIFIED** |
| 34 | Capture a live interview via Recall (needs a key + tunnel) | **UNVERIFIED** |
| 35 | AI feedback appears on a completed round | **UNVERIFIED** |

If you run these, the order above is the golden path. Step 31 is the one most
likely to bite: if you land back on the login page, check the Supabase redirect
URL allow-list (`docs/setup/supabase.md` step 4) before anything else.

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
