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
```

Then, in order:

1. **[`docs/setup/supabase.md`](docs/setup/supabase.md)** — create a free
   project, run [`schema.sql`](schema.sql) in the SQL editor, paste three keys
   into `.env`. Ten minutes, and the only required step.
2. *(optional)* **[`docs/setup/recall.md`](docs/setup/recall.md)** — an API key
   and a tunnel, if you want real meeting capture.

```bash
docker compose up -d --build
make verify
```

`make verify` prints one line per service and the URL map. Open
<http://localhost:3005>.

## What runs where

Eleven containers:

| | |
|---|---|
| `landing` :3000 | login; sets the shared auth cookie |
| `recruiter-app` :3005 | the dashboard |
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
