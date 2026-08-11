# Self-host Settings UI — design

**Status:** approved design, not yet planned
**Date:** 2026-08-11
**Sub-project 1 of 4** in the "easy self-hosted setup" effort (see §Out of scope).

## Goal

`docker compose up -d` → open one URL → fill in what you have → save → use the
product. No hand-editing `.env` before the first successful boot, and no reading
four setup docs to discover which of 38 variables matter.

Success is measured by one thing: **a new self-hoster with a Supabase account and
an Anthropic key reaches a working intake call without opening a text editor.**

## Context that shapes this

Established by inspection of the repo on 2026-08-11. Each of these changed the
design; none should be re-derived.

1. **The LLM gateway migration (phases 1–8, complete) is the enabler.** All 27
   model choices are now named per-workload aliases in one file,
   `litellm-config.yaml`, and no application module holds a provider key. "Configure
   models per task" is a view over one file read by one service. Before that
   migration it would have been 9+ scattered call sites.
2. **`admin-app` is not the place.** It is a staff SaaS portal (customers,
   subscriptions, promotions) and it depends on the backend. Operator settings for
   a self-hoster is a new surface.
3. **Most services already degrade without config.** `docs/architecture.md`
   §"Degrading without keys" documents per-feature consequences for every optional
   dependency. **Supabase is the only hard requirement.**
4. **38 variables across 12 services**, all read from `.env` at process start.
5. **9 of those 38 cannot be applied by a restart.** `recruiter-app/Dockerfile:17-24`
   declares `NEXT_PUBLIC_*` as build ARGs set as ENV before `RUN bun run build`
   at :31; Next.js inlines them into the client bundle at build time. Two of the
   nine are `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` — the
   exact values first-run setup must write. `next.config` sets
   `output: 'standalone'`, so a Node server does run and `process.env` IS live
   server-side (`middleware.ts` already relies on this); only the browser bundle
   is frozen.
6. **`schema.sql` is not idempotent** — 53 `CREATE TABLE` against 6
   `IF NOT EXISTS`, plus bare `CREATE TYPE ... AS ENUM`. Re-running it errors.
7. **`.env.example` carries 95 comment lines.** The file stays hand-editable, so
   a rewrite must preserve comments and key order.

## Decisions

| # | decision | rejected alternative, and why |
|---|---|---|
| D1 | **Write `.env` + restart affected containers.** | A runtime config store read by all 12 services: coherent, but a large refactor with an unavoidable bootstrap problem. The env-var model is what the services already use and what self-hosters already understand. |
| D2 | **Scope-restricted socket proxy, never the raw socket.** | Mounting `/var/run/docker.sock` into `setup-ui` is root-equivalent on the host. `tecnativa/docker-socket-proxy` permits only container inspect + restart; create, exec and binds are refused at the proxy. |
| D3 | **`setup-ui` always boots; other services degrade.** | A two-phase compose profile means the plain `up` users already know does the wrong thing. Fact 3 means most of the degradation already exists. |
| D4 | **Supabase stays external; the UI guides it and applies the schema.** | Bundling Supabase's self-host stack (~8 containers) is the only true zero-cloud start but means owning its upgrades for every user. Revisit as its own sub-project. |
| D5 | **Password set on first visit, bound to `127.0.0.1` by default.** | A token printed to logs is invisible under `docker compose up -d`, which is how people actually start it. Password is defence-in-depth *behind* the localhost bind, not instead of it. |
| D6 | **Inject frontend config at runtime from the Node server.** | Rebuilding images on save takes minutes and needs the build endpoint opened in the proxy D2 just locked down. Marking them read-only would mean the most important first-run value cannot be set from the setup UI. |
| D7 | **Config files stay the source of truth.** | The UI is a front end to `.env` and `litellm-config.yaml`, not a replacement store. Nothing becomes unreachable if the UI breaks. |

## Architecture

```
docker compose up -d
   │
   ├─ setup-ui  :3010  (bound 127.0.0.1)  ── no dependencies, always boots
   │     │  reads/writes  .env  +  litellm-config.yaml   (atomic, backed up)
   │     │  applies       schema.sql / seed.sql → Supabase
   │     └─ talks to ───► socket-proxy ──► /var/run/docker.sock
   │                       (inspect + restart only)
   │
   └─ the 12 app services ── read .env at start, degrade when unset
```

### Components

**`setup-ui`** — FastAPI + a static frontend. Owns config file I/O, validation,
Supabase provisioning, health aggregation, and restart orchestration. Imports no
application code and has no Supabase dependency; that is what lets it boot into
an empty stack.

**`socket-proxy`** — `tecnativa/docker-socket-proxy` sidecar, `CONTAINERS=1`,
`POST=1`, everything else off. `setup-ui` never sees the real socket.

**`var_map.yaml`** — declarative `variable → [services]`. Drives restart scope
and the "these containers will bounce" confirmation. A test asserts every key in
`.env.example` appears here (see §Testing).

**Runtime config injection** — each Next app's root layout reads `process.env`
server-side and emits `window.__CFG__` once; client code reads that instead of
inlined `NEXT_PUBLIC_*`. Build ARGs are removed from the four Dockerfiles.

## Config surface

Eight groups, ordered by what blocks what. Each shows ✅ configured /
⚠️ optional-unset / ❌ required-missing, so the landing screen *is* the checklist.
The "unset ⇒" column is a direct lift of `docs/architecture.md` §"Degrading
without keys".

| group | holds | unset ⇒ |
|---|---|---|
| 1 Database *(required)* | Supabase URL, service key, anon key | nothing works |
| 2 AI models | provider keys + model-per-task | all agents off |
| 3 Voice | Deepgram, TURN | voice cannot transcribe |
| 4 Meeting capture | Recall key, webhook URL/secret | no callbacks |
| 5 Knowledge graph | Neo4j, OpenAI embeddings | graph degrades |
| 6 Connectors | MCP signing key, MCP URL | MCP returns 503 |
| 7 Email | provider + token | no outbound mail |
| 8 Advanced | everything else, raw key/value | — |

### Models per task

A view over `litellm-config.yaml`'s 27 aliases. Two tiers:

- **Quick** (default) — "use one provider for everything": one key, one tier, and
  all 23 Anthropic aliases fill in. One decision to a working stack.
- **Advanced** — the per-task table (`intake-text`, `voice-screening`,
  `resume-extract`, …), each with its own provider and model. This is what the
  migration was for: pointing `intake-jd` at local Gemma while the rest stay
  hosted.

Two constraints the picker encodes automatically, both learned in production
during the migration:

- Aliases that send tools must keep `supports_function_calling: true`. A `false`
  there **disables** the agent rather than degrading it — streaming and emulated
  tools do not compose, so the JSON arrives as prose and is never parsed.
- An OpenAI reasoning model needs `additional_drop_params: ["temperature"]`.
  Nine call sites send `temperature=0` and GPT-5 models accept only the default;
  global `drop_params` does not help because the param IS supported and only the
  value is rejected.

### Secrets in the UI

Write-only. Fields render as `•••• set` with *Replace* / *Clear*; the API never
returns a stored secret to the browser. `.env` on disk stays plaintext — it
already is, and encrypting it while the Docker socket is one hop away would be
theatre.

## Data flow — save & apply

1. Client sends **only changed keys**.
2. Validate (format; cheap reachability where meaningful). Reject before writing.
3. Compute affected services from `var_map.yaml`.
4. Confirm to the user which containers will restart, explicitly warning that
   **active voice calls will drop**.
5. On confirm:
   a. back up `.env` → `.env.bak.<timestamp>`
   b. write `.env` atomically (temp file + fsync + rename), preserving comments
      and key order
   c. write `litellm-config.yaml` the same way if aliases changed
   d. restart affected services **one at a time** via the socket proxy
   e. poll each service's health with a timeout
   f. report per-service result
6. On failure: surface a `docker logs` tail inline and offer one-click rollback
   (restore the backup, restart again).

### Supabase provisioning

Check a sentinel (`public.organizations`) first. If present, report "already
provisioned" and do nothing — fact 6 means a blind re-run errors. If absent, run
`schema.sql` then `seed.sql` and report what was created.

## Error handling

- Validation precedes every write; a failed value is never persisted.
- Timestamped backups; rollback is one click.
- Restart failures show logs, not a spinner.
- Health polling always has a timeout; the UI never hangs.
- Login is rate-limited — it guards a Docker socket.
- First-run claim race: whoever reaches an unclaimed instance sets the password.
  Harmless behind the default localhost bind; the UI warns if the bind was
  widened.
- Forgotten password: delete the hash file on the volume. Requires host access,
  which is the correct bar.

## Testing

| test | why it exists |
|---|---|
| every key in `.env.example` appears in `var_map.yaml` | a new variable must not silently become unmanaged — the map is the whole restart-scoping mechanism |
| `.env` round-trip preserves all 95 comments and key order | the file stays hand-editable; mangling it is user-hostile |
| the API never returns a stored secret | write-only is the entire secret posture |
| after saving Supabase creds, **browser-visible** runtime config changes | pins fact 5. Without it, setup reports success while the browser keeps stale values and login fails with no explanation |
| saving a var restarts only its mapped containers | over-broad restarts drop voice calls for no reason |
| applying schema twice reports "already provisioned" rather than erroring | fact 6 |
| atomic write survives an interrupted save | a half-written `.env` bricks the stack |

E2E: empty `.env` → `up -d` → set password → paste Supabase creds → apply schema
→ add one provider key → log into recruiter-app. That path is the goal statement,
executed.

## Out of scope

Deliberately excluded; each is its own sub-project with its own spec:

- **Public URL / tunnel** — Recall webhook URL, MCP URL for Claude, and the
  voice-frontend the meeting bot loads as its camera. One problem with three
  consumers.
- **WebRTC media path (TURN)** — the meeting-bot↔voice-agent UDP blocker.
  `voice-agent/src/config.py` already has `turn_server_url` / `turn_username` /
  `turn_credential`, so this is likely configuration and guidance, not new code.
- **Guided setup checklist** — the manual Recall-portal and Claude-connector
  steps, walked through in the UI. Depends on all of the above.
- **Bundled local Supabase** (D4's rejected alternative).
