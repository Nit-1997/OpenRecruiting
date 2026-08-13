# OpenRecruiting

An open-source, self-hostable recruiting platform: AI-run intake calls, candidate
and interview-round management, meeting capture with AI-generated interview
feedback, a WebRTC voice agent, and a recruiting knowledge graph. Apache-2.0.

> Originally built as **Mazle**. This is an **archived reference release** — it
> is not maintained and issues may not be answered. It is published so the work
> is readable and forkable, not because anyone is supporting it.

## Quick start

```bash
git clone https://github.com/Nit-1997/OpenRecruiting.git && cd OpenRecruiting
cp .env.example .env
docker compose up -d --build
```

Then open **<http://127.0.0.1:3010>** — the setup UI. Choose a password, and it
walks you through the rest: every setting grouped by what it enables, live
container health, and a Save button that restarts only the services a change
affects. No hand-editing `.env` first.

It boots even when nothing else is configured, which is the point. Every
dependency except the database is optional — an unset key disables that feature
rather than breaking the stack, and the UI tells you which.

**The one thing it cannot do for you** is create your database. Supabase needs a
project (free tier is fine) and `schema.sql` pasted into its SQL editor: the
service key can read your data but cannot run DDL, so nothing here can apply a
schema on your behalf without a database superuser password we deliberately do
not ask for. The setup UI detects whether the schema is applied and gives you
the exact steps and your project's own link. See
[`docs/setup/supabase.md`](docs/setup/supabase.md).

Optional, when you want them:

- **[`staff_user.sql`](staff_user.sql)** — provisions a staff account for the
  admin portal on :3001. Edit the CONFIG block and run it.
- **[`docs/setup/recall.md`](docs/setup/recall.md)** — an API key and a tunnel,
  for real meeting capture.

```bash
make verify
```

`make verify` prints one line per service and the URL map. Open
<http://localhost:3005>.

<details>
<summary>Prefer editing <code>.env</code> by hand?</summary>

Nothing stops you — `.env` is still the source of truth and the setup UI is only
a front end to it, comments and ordering preserved. It writes a timestamped
backup before every save. If you never open :3010, the stack behaves exactly as
it always did.

The setup UI binds to `127.0.0.1` and is not reachable from the network, because
it can edit every secret and restart containers. To reach it on a remote host,
tunnel: `ssh -L 3010:localhost:3010 user@host`.
</details>

## What runs where

Twelve containers:

| | |
|---|---|
| `landing` :3000 | login; sets the shared auth cookie |
| `recruiter-app` :3005 | the dashboard |
| `admin-app` :3001 | staff portal: organizations and their credit budgets, requisitions, blog |
| `backend` :8004 | FastAPI, everything under `/api/v2/*` |
| `feedback-agent`, `intake-agent`, `intake-context-builder` | background workers (internal-only) |
| `cortex-backend` :8010, `cortex-mcp` :8020, `neo4j` :7474 | the knowledge graph |
| `voice-agent` :8011, `voice-frontend` :3003 | WebRTC voice calls |

You bring three cloud services: **Supabase** (database and auth — required),
**Recall.ai** (meeting bots — optional), and **OpenAI / Anthropic / Deepgram**
(LLM and speech — optional). A feature whose key is missing is disabled, not
broken: the stack still comes up.

**The one asterisk:** Recall is a cloud service that calls *your* backend, so
live meeting capture needs a public URL. On a laptop that means
`ngrok http 8004`. Everything else works without it.

## Docs

| | |
|---|---|
| [Architecture](docs/architecture.md) | service map, auth flow, the job seam, how things degrade |
| [Security](docs/security.md) | trust boundaries, the RLS model, what is left to you |
| [Supabase setup](docs/setup/supabase.md) | the required ten minutes |
| [Recall setup](docs/setup/recall.md) | meeting capture and the tunnel |
| [E2E checklist](docs/e2e-checklist.md) | what was verified before release — and what wasn't |
| [Engineering notes](docs/blog/README.md) | how it was extracted, and what broke |

## Development

```bash
make build        # build every image
make up           # start everything
make logs         # tail
make test         # backend suite (Python 3.11 in Docker)
make down         # stop
```

Frontend tests run per-app with `bun test <dir>`. In `recruiter-app`, run
**directory slices** — a bare `bun test` is known to hang.

Linux users can give the voice agent host networking for a better media path:

```bash
docker compose -f docker-compose.yml -f docker-compose.linux.yml up -d
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
