# OpenRecruiting

An open-source, self-hostable recruiting platform: AI-run intake calls, candidate
and interview-round management, meeting capture with AI-generated interview
feedback, a WebRTC voice agent, and a recruiting knowledge graph. Apache-2.0.

> Originally built as **Mazle**. Support is best-effort and issues may take a
> while, but the project is meant to be run — PRs welcome.

## Setting it up

**→ [setup-wiki-docs/](setup-wiki-docs/README.md) is the full walkthrough.**
Roughly 90 minutes, most of it spent creating accounts rather than configuring
software.

```bash
git clone https://github.com/Nit-1997/OpenRecruiting.git && cd OpenRecruiting
cp .env.example .env
docker compose up -d --build
```

Then open **<http://127.0.0.1:3010>** — the setup UI. Choose a password, and it
takes it from there: every setting grouped by what it enables, live container
health, a readiness panel showing which features are actually working, and a Save
button that restarts only the services a change affects. No hand-editing `.env`.

**What you need to bring.** Seven accounts, none of them optional if you want to
run a real interview:

| | |
|---|---|
| [Supabase](setup-wiki-docs/supabase.md) | database and sign-in |
| [Anthropic](setup-wiki-docs/ai-keys.md) | intake, feedback, screening |
| [Deepgram](setup-wiki-docs/ai-keys.md) | speech-to-text |
| [Recall.ai](setup-wiki-docs/recall.md) | the bot that joins and records |
| [Cloudflare](setup-wiki-docs/cloudflare.md) | domain, tunnel, TURN relay |
| [Resend](setup-wiki-docs/email.md) | invitations, feedback links, resets |

The stack *starts* with any of these unset — an unset key disables that feature
rather than breaking the boot, and the readiness panel tells you which. But an
instance missing Recall, the tunnel or TURN cannot capture an interview, and one
missing email never contacts a candidate. Genuinely optional:
[Google sign-in](setup-wiki-docs/google-auth.md), which model each workload uses, and
the Cortex MCP connector.

**The one thing the setup UI cannot do for you** is create your database.
Supabase needs a project (free tier is fine) and `schema.sql` pasted into its SQL
editor: the service key can read your data but cannot run DDL, so nothing here
can apply a schema without a database password we deliberately do not ask for.
The UI detects whether the schema is applied and gives you the exact steps.

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

**Why a domain is not negotiable.** Recall runs in its own cloud and calls *your*
backend when a recording finishes, so it needs a public address — that is the
Cloudflare tunnel. The bot's audio is a separate problem: media is UDP, which no
HTTP tunnel carries, which is what the TURN relay is for. Everything is served
through **one hostname**, path-routed by Caddy; the frontends expect the voice
agent on the same origin, so splitting across subdomains breaks voice and MCP.

## Docs

| | |
|---|---|
| **[Setup](setup-wiki-docs/README.md)** | **start here — clone to working instance** |
| [Supabase](setup-wiki-docs/supabase.md) | database, keys, schema, staff access |
| [Cloudflare](setup-wiki-docs/cloudflare.md) | domain, tunnel, TURN relay |
| [Recall](setup-wiki-docs/recall.md) | meeting capture and webhooks |
| [AI keys](setup-wiki-docs/ai-keys.md) | Anthropic, Deepgram, OpenAI, model choice |
| [Email](setup-wiki-docs/email.md) | Resend or Zoho |
| [Google sign-in](setup-wiki-docs/google-auth.md) | optional OAuth |

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
