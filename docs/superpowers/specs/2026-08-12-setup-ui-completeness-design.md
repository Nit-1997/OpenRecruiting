# Setup UI completeness

Status: approved, not implemented
Date: 2026-08-12

## Why

OpenRecruiting is about to be published. Someone who clones the repo should be
able to reach a working instance by following one guide, and the setup UI at
`:3010` is what that guide points at. Three things stop that today.

This is sub-project **A** of three. **B** is the setup wiki (a linear
production guide plus a how-to per provider); **C** is an agent skill that
drives A and reads B. A goes first so B describes finished behaviour and is
written once. Each gets its own spec.

## Scope

In: `schema.sql` re-run safety, `CLOUDFLARE_TOKEN` as a managed setting, and a
feature-readiness view in the setup UI.

Out: the wiki itself, the agent skill, and any change to how credentials are
collected. In particular the setup UI still does **not** ask for the Supabase
database password — `app/supabase_setup.py` documents that trade and this spec
does not reopen it.

---

## 1. `schema.sql` becomes atomic and guarded

### Problem

`schema.sql` is the bootstrap artifact: `README.md` and `docs/setup/supabase.md`
both tell the reader to paste it into Supabase's SQL editor. It is not
idempotent and not transactional, so it fails badly in the two ways a
first-timer actually hits.

Measured against a clean Postgres 17 + pgvector database:

| Scenario | Today | Required |
|---|---|---|
| First run | 48 tables, clean | unchanged |
| Run a second time | **502 errors**, database half-mutated | one clear error, zero changes |
| Failure part-way through | half-built database, no clean recovery | full rollback |

The second row is the common case: the SQL editor times out or someone is
unsure whether it worked, so they run it again.

### Design

Wrap the file in a single transaction and add a guard immediately before the
first executable statement (the `CREATE EXTENSION` block, currently line 45),
leaving the provenance banner at the top:

```sql
BEGIN;

DO $guard$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema = 'public' AND table_name = 'organizations') THEN
    RAISE EXCEPTION 'OpenRecruiting schema is already applied to this database. Nothing was changed.';
  END IF;
END
$guard$;

-- ... existing 9,600 lines ...

COMMIT;
```

`organizations` is the sentinel because it is the root of the tenancy model and
can never legitimately be absent from a provisioned project. `app/supabase_setup.py`
already uses the same table for its REST-based check, so the two agree by
construction.

### Why not full idempotency

Making every statement re-runnable means ~500 mechanical edits: 48 tables, 61
functions, 136 indexes, 80 policies and 156 constraints. Policies and
constraints have no `IF NOT EXISTS`, so each needs a `DO` block. That is a large
diff on a generated file, each edit an opportunity to change semantics silently,
and it makes a future `pg_dump` refresh much harder to reconcile. The guard plus
the transaction gets the user-visible benefit for ~12 lines.

The one case it does not cover is repairing a partially applied schema — but the
transaction removes that state, so there is nothing left to repair.

### Verification

Already measured on `pgvector/pgvector:pg17` with a minimal Supabase stand-in
(`extensions` and `auth` schemas, the three roles, `auth.users`, and stubs for
`auth.uid/role/jwt`):

- first run exits 0 and creates 48 tables;
- second run emits exactly one error and leaves the table count at 48;
- a deliberate `SELECT 1/0` before `COMMIT` leaves **zero** tables behind.

The implementation plan must re-run all three against the final file.

### Regeneration hazard

`schema.sql` is generated. A future refresh from `pg_dump` will not contain the
wrapper, and a silent loss reintroduces the 502-error path. The banner gains an
explicit note that the `BEGIN`/guard/`COMMIT` must be re-applied after any
regeneration.

---

## 2. `CLOUDFLARE_TOKEN` becomes a managed setting

### Problem

`docker-compose.yml:300` reads it:

```yaml
command: tunnel --no-autoupdate run --token ${CLOUDFLARE_TOKEN:-}
```

It appears in neither `.env.example` nor `setup-ui/app/varmap.py`. The setup UI
therefore cannot set the tunnel, even though the tunnel is required for meeting
capture — Recall is cloud-only and calls back into the instance. Any guide
written against today's code has to interrupt itself to say "now hand-edit
`.env`", which undercuts the point of the setup page.

### Design

Add `CLOUDFLARE_TOKEN` to `.env.example`, and to the **Domains** (`urls`) group
in `varmap.py` as a secret with `services=["cloudflared"]`.

Domains is the right group: the token and `PUBLIC_BASE_URL` are two halves of
one decision — the instance's public address — and only one half is currently
settable.

Restart scoping is already correct for this. The applier runs
`docker compose up -d --no-build`, which **recreates** rather than restarts, so
the changed `${CLOUDFLARE_TOKEN}` interpolation in `command:` takes effect. A
plain Docker restart would not have, because the command is resolved at
container-create time.

### Verification

`tests/test_varmap.py` enforces both halves automatically: one test fails if a
mapped variable is absent from `.env.example`, another fails if a backend
setting is neither mapped nor listed in `UNMANAGED`. No new test is needed for
the mapping itself. The plan should additionally confirm that saving the token
recreates `cloudflared` and that the tunnel connects.

---

## 3. Feature readiness

### Problem

The setup UI reports two things: container state (`/api/health`) and whether the
schema is applied (`/api/database`). Neither answers the question a first-time
operator actually has — *what works right now, and what have I not finished?*

Several features fail silently when a key is missing, and the failure does not
look like a configuration problem:

- `LAMBDA_CALLBACK_SECRET` unset: the backend rejects every worker callback, so
  feedback results never come back. Nothing reports this.
- `RECALL_WEBHOOK_SECRET` unset: bots join calls and every callback is
  rejected, so nothing is ever captured.
- `EMAIL_PROVIDER` unset: no interview invitations, feedback links or password
  resets are sent.
- `TURN_*` unset: browser voice works, meeting-bot voice cannot reach the agent.

### Design

A new module `setup-ui/app/readiness.py` exposing a **pure function** from the
`.env` values to a list of features:

```python
@dataclass(frozen=True)
class Feature:
    id: str
    name: str
    state: str            # "live" | "partial" | "dormant" | "unknown"
    missing: list[str]    # variable names still needed
    consequence: str      # what does not work while it is not live

def evaluate(values: dict[str, str]) -> list[Feature]: ...
```

Purity is the point: no Docker calls, no network, no file reads. It is a
lookup table plus presence checks, so it is exhaustively unit-testable and
cannot fail at runtime in a way that breaks the page.

Exposed as `GET /api/readiness` (behind `require_auth`, like every other data
endpoint) and rendered as a panel in `app/static/index.html`.

Feature map:

| Feature | Requires | Consequence when missing |
|---|---|---|
| Core | `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_JWT_SECRET`, `ANTHROPIC_API_KEY`, `LITELLM_MASTER_KEY` | nothing works |
| Meeting capture | `RECALL_API_KEY`, `RECALL_WEBHOOK_SECRET`, `PUBLIC_BASE_URL`, `CLOUDFLARE_TOKEN` | no bot can join, or joins and captures nothing |
| Browser voice | `DEEPGRAM_API_KEY` | voice agent starts but cannot transcribe |
| Meeting-bot voice | browser voice + `TURN_SERVER_URL`, `TURN_USERNAME`, `TURN_CREDENTIAL` | bot cannot reach the agent through NAT |
| Email | `EMAIL_PROVIDER`, `EMAIL_FROM_ADDRESS`, and the matching provider key | no invitations, feedback links or password resets |
| Knowledge graph | `NEO4J_PASSWORD`, `CORTEX_INTERNAL_SECRET`, `OPENAI_API_KEY` | no graph, no Cortex answers |
| MCP connector | `MCP_JWT_KEY_ID`, `MCP_JWT_PRIVATE_KEY_PEM`, `PUBLIC_BASE_URL` | discovery returns 503 |
| ATS sync | `KNIT_API_KEY` | no ATS sync |
| Worker callbacks | `LAMBDA_CALLBACK_SECRET` | feedback results never return |
| Google sign-in | *not determinable from `.env`* | always `unknown` — see below |

`partial` means some but not all of a feature's variables are set — the state
worth surfacing loudest, because it looks configured and is not.

Core's row covers only its **environment** prerequisites. Whether the schema has
been applied is a separate question answered by `/api/database`, which makes a
live REST call; `readiness.py` stays pure and does not duplicate it. The page
shows both, and the guide in B sequences them.

### Honesty constraint

Google sign-in is configured in the Supabase dashboard, not in `.env`. The
service key cannot read auth provider settings, so this module **cannot** know
whether it is enabled. It renders as `unknown` with a link to the how-to, never
as a green tick it has not earned.

This is the same discipline as `app/supabase_setup.py`: report what is actually
measurable and hand over exact steps for the rest. A readiness panel that
guesses is worse than one that admits a gap — the failure mode this codebase
keeps producing is "looks applied, isn't".

### Verification

- `tests/test_readiness.py`: table-driven over `evaluate()`. Every feature gets
  a live case, a dormant case, and a partial case; plus a test that Google auth
  is always `unknown` regardless of env contents.
- `tests/test_api.py`: `/api/readiness` requires auth and returns the schema.

---

## Risks

**The schema wrapper is lost on regeneration.** Mitigated by the banner note;
not enforceable in code, since the dump is produced outside this repo.

**The readiness map drifts from reality.** A feature gains a required variable
and the panel keeps reporting `live`. Partly mitigated by `test_varmap.py`
already forcing every backend setting to be mapped or explicitly excluded, but
readiness groupings are a separate judgement. Accepted: the panel is advisory,
and every entry names the variables it checked so a wrong answer is traceable.

**`CLOUDFLARE_TOKEN` is a secret in `.env`.** Consistent with every other
secret the setup UI already manages; no new exposure.

## Out of scope, noted for B

Documentation-only findings from the audit that the wiki must cover:

- `SUPABASE_JWT_SECRET` and `DEEPGRAM_API_KEY` are easy to miss — both are
  required-tier but absent from most mental models of "the Supabase keys".
- Google auth's real failure was a `NEXT_PUBLIC_` browser URL being fetched
  server-side in the callback. The how-to must call this out.
- Caddy serves **one** hostname with path routing (`/voice-ws-v2`, `/mcp`,
  catch-all). Four subdomains would break voice and MCP.
- The schema must be applied before the apps work, but the setup UI's schema
  check needs the Supabase URL and key first — so the order is: enter keys →
  UI reports the schema is missing → apply it → re-check.
