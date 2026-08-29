# OpenRecruiting

**An open-source, self-hosted recruiting platform with AI intake calls, interview
recording, and automatically written interview feedback.** Runs on your own
servers, on twelve Docker containers, under Apache-2.0. Candidate recordings and
transcripts never leave infrastructure you control.

Originally built as **Mazle**, a venture-backed recruiting product. The company
wound down and the code was opened rather than deleted.

> **This project is not maintained.** No one is fixing bugs, reviewing pull
> requests, or answering issues. It ran a real company and it still runs, but you
> are on your own with it. Fork it freely. If you depend on any part, pin a
> commit, because `main` can move without warning.

## Start here

Three kinds of people land on this page. Pick your door.

| You are | You want | Go to |
|---|---|---|
| **A company or HR team** wanting to run your own recruiting stack | The whole platform, self-hosted, no SaaS vendor holding your candidate data | [Run the whole thing](#run-the-whole-thing) |
| **An engineer** who came for one component | The AI client, the voice agent, or the MCP server, without the recruiting product attached | [Take just one piece](#take-just-one-piece) |
| **A founder or builder** in HR tech | What was built, what it cost, and which decisions were load-bearing | [Design notes](#design-notes) |

## What it does

- **AI intake calls.** An agent talks to the hiring manager, by voice or chat, and turns a vague request into a structured job requisition with interview rounds and a scorecard.
- **Candidate screening.** Generated screening questions, an AI assessor, and shareable candidate-facing links.
- **Interview recording.** A bot joins the Google Meet, Zoom, or Teams call and records it.
- **Automatic interview feedback.** After the call, the agent interviews the *interviewer* by voice and writes the scorecard from that conversation, which is the part people forget to do.
- **Debrief packets.** One document per candidate pulling every round together, with a chat agent over it.
- **A recruiting knowledge graph.** Every interview feeds a temporal graph, so hiring patterns compound instead of evaporating.
- **Ask questions from Claude.** A read-only [MCP](https://modelcontextprotocol.io/) server exposes your own slice of that graph to Claude, Claude Code, or any MCP client.
- **ATS sync.** Dedicated adapters for Ashby and Workable, plus a [Knit](https://www.getknit.dev/) unified connector that reaches Greenhouse, Lever, and others.
- **Multi-tenant from the ground up.** 189 organization-scoped references, 48 row-level security policies, and per-organization credit budgets.
- **Bring your own model, including a local one.** Every service calls a [LiteLLM](https://docs.litellm.ai/) gateway rather than a vendor SDK, and workloads are named by job (`intake-jd`, `feedback-condense`) so you repoint them one at a time. Ollama entries are already wired up if you want models that never leave your machine.

## Take just one piece

You do not need to clone the recruiting platform to use the parts inside it. Pip
installs a subdirectory straight from git, so a folder here is already a package.

| Component | What it is | How to take it |
|---|---|---|
| **[`llm-core`](llm-core/README.md)** | Provider-agnostic LLM client. Emulates tool calling on models that lack it, probes the gateway for which models can do what, and ships a fake client plus a pytest fixture so you can test with no API key. Zero internal dependencies. | `pip install "git+https://github.com/Nit-1997/OpenRecruiting.git#subdirectory=llm-core"` |
| **[`intake-core`](intake-core/README.md)** | The intake agent's state machine, prompts, tools, and coverage tracker, shared unchanged across voice, chat, and two Lambdas. Honest caveat: it pulls in the Supabase client. | `pip install "git+https://github.com/Nit-1997/OpenRecruiting.git#subdirectory=intake-core"` |
| **[`cortex-mcp`](cortex-mcp/README.md)** | Read-only multi-tenant MCP server over Neo4j. Three composable tools instead of a catalogue of ten, and a middleware that force-binds `$org_id` into every query so cross-tenant reads are structurally impossible. | Read and copy. Start with the auth middleware. |
| **[`voice-agent`](voice-agent/README.md)** | Real-time voice over WebRTC using [Pipecat](https://github.com/pipecat-ai/pipecat), running inside a [Recall.ai](https://www.recall.ai/) bot so the agent can speak on a live meeting. Deepgram in, Claude in the middle, Deepgram out. | Read and copy. The pipeline is 14 frame processors. |
| **`setup-ui`** | A self-hosting config screen. Groups every setting by what it enables, shows live container health, and restarts only the services a change affects. | Read and copy. |

The first two install and run today. The last three are running services, not
libraries, so what is worth taking is the design.

## Run the whole thing

**→ [setup-wiki-docs/](setup-wiki-docs/README.md) is the full walkthrough.** About
90 minutes, most of it spent creating accounts rather than configuring software.

Using Claude Code? Open it in the clone and say *"help me set up
OpenRecruiting"*. The repo ships a skill that walks the guide with you, writes
the config, and verifies each step.

```bash
git clone https://github.com/Nit-1997/OpenRecruiting.git && cd OpenRecruiting
cp .env.example .env
docker compose up -d --build
```

Then open **<http://127.0.0.1:3010>**, the setup UI. Choose a password and it
takes over from there. Every setting is grouped by what it enables, with live
container health, a readiness panel showing which features actually work, and a
save button that restarts only the services a change affects. No hand-editing
`.env`.

### Accounts you need to bring

Six services, none optional if you want to run a real interview.

| Service | What it gives you |
|---|---|
| [Supabase](setup-wiki-docs/supabase.md) | Database and sign-in |
| [A model provider](setup-wiki-docs/ai-keys.md) | Intake, feedback, screening. Pick **one** of Anthropic, OpenAI, or [OpenRouter](llm-providers.example.json). Ollama runs models locally. |
| [Deepgram](setup-wiki-docs/ai-keys.md) | Speech to text |
| [Recall.ai](setup-wiki-docs/recall.md) | The bot that joins and records |
| [Cloudflare](setup-wiki-docs/cloudflare.md) | Domain, tunnel, TURN relay |
| [Resend](setup-wiki-docs/email.md) | Invitations, feedback links, resets |

The stack starts with any of these unset. An unset key disables that feature
rather than breaking the boot, and the readiness panel tells you which. But an
instance missing Recall, the tunnel, or TURN cannot capture an interview, and one
missing email never contacts a candidate. Genuinely optional: [Google
sign-in](setup-wiki-docs/google-auth.md), which model each workload uses, and the
Cortex MCP connector.

### The one thing the setup UI cannot do for you

Create your database. Supabase needs a project, and the free tier is fine, with
`schema.sql` pasted into its SQL editor. The service key can read your data but
cannot run DDL, so nothing here can apply a schema without a database password we
deliberately do not ask for. The UI detects whether the schema is applied and
gives you the exact steps.

```bash
make verify
```

`make verify` prints one line per service and the URL map. Then open
<http://localhost:3005>.

<details>
<summary>Prefer editing <code>.env</code> by hand?</summary>

Nothing stops you. `.env` is still the source of truth and the setup UI is only a
front end to it, comments and ordering preserved. It writes a timestamped backup
before every save. If you never open :3010, the stack behaves exactly as it
always did.

The setup UI binds to `127.0.0.1` and is not reachable from the network, because
it can edit every secret and restart containers. To reach it on a remote host,
tunnel it:

```bash
ssh -L 3010:localhost:3010 user@host
```
</details>

## What runs where

Eighteen containers. These are the ones you interact with:

| Container | Port | Role |
|---|---|---|
| `landing` | 3000 | Login. Sets the shared auth cookie. |
| `recruiter-app` | 3005 | The dashboard |
| `admin-app` | 3001 | Staff portal: organizations, credit budgets, requisitions, blog |
| `setup-ui` | 3010 | The config screen. Bound to localhost only. |
| `backend` | 8004 | FastAPI, everything under `/api/v2/*` |
| `cortex-backend` | 8010 | Knowledge graph ingestion |
| `cortex-mcp` | 8020 | MCP server |
| `neo4j` | 7474, 7687 | Graph database. Localhost only, for the browser console and cypher-shell. |
| `voice-agent` | 8011 | WebRTC voice |
| `voice-frontend` | 3003 | The page the Recall bot loads |

And these run in the background:

| Container | Role |
|---|---|
| `feedback-agent`, `intake-agent`, `intake-context-builder` | Background workers |
| `litellm` | The model gateway every service calls instead of a vendor SDK |
| `caddy` | Path-routes everything through one hostname |
| `cloudflared` | The tunnel that gives Recall a public address to call back |
| `applier`, `socket-proxy` | Let the setup UI restart containers without ever holding the Docker socket. The proxy allows exactly two calls, list and restart. The applier holds the socket but opens no port, and reads only a request file. |

## Design notes

The decisions that were expensive to learn, written down where they happened.

| Note | Where |
|---|---|
| Why one hostname, and why a tunnel alone is not enough | [below](#why-a-domain-is-not-negotiable) |
| Why three MCP tools beat a catalogue of ten | [cortex-mcp/README.md](cortex-mcp/README.md) |
| How the knowledge graph ingests, and the three-tier ontology | [cortex-v2-design.md](cortex-backend/docs/cortex-v2-design.md) |
| The 14-processor voice pipeline, and how interruptions flow backwards | [voice-agent/README.md](voice-agent/README.md) |
| Why forcing a tool call is not cosmetic, measured at 8.75% | [llm-core/README.md](llm-core/README.md) |
| Which parts of the recruiter app are real and which are mocked | [REAL-VS-MOCK-MATRIX.md](recruiter-app/docs/REAL-VS-MOCK-MATRIX.md) |
| How a config UI restarts containers without holding the Docker socket | [docker-compose.yml](docker-compose.yml), `socket-proxy` and `applier` |

### Why a domain is not negotiable

Recall runs in its own cloud and calls *your* backend when a recording finishes,
so it needs a public address. That is the Cloudflare tunnel.

The bot's audio is a separate problem. Media is UDP, which no HTTP tunnel
carries, and that is what the TURN relay is for.

Everything is served through **one hostname**, path-routed by Caddy. The
frontends expect the voice agent on the same origin, so splitting across
subdomains breaks voice and MCP.

## Documentation

| Guide | Covers |
|---|---|
| **[Setup](setup-wiki-docs/README.md)** | **Start here. Clone to working instance.** |
| [Supabase](setup-wiki-docs/supabase.md) | Database, keys, schema, staff access |
| [Cloudflare](setup-wiki-docs/cloudflare.md) | Domain, tunnel, TURN relay |
| [Recall](setup-wiki-docs/recall.md) | Meeting capture and webhooks |
| [AI keys](setup-wiki-docs/ai-keys.md) | Anthropic, Deepgram, OpenAI, model choice |
| [Email](setup-wiki-docs/email.md) | Resend or Zoho |
| [Google sign-in](setup-wiki-docs/google-auth.md) | Optional OAuth |
| [Contributing](CONTRIBUTING.md) | Conventions, if you are forking |
| [Security](SECURITY.md) | Reporting a vulnerability |

## Development

```bash
make build        # build every image
make up           # start everything
make logs         # tail
make test         # backend suite (Python 3.11 in Docker)
make down         # stop
```

Frontend tests run per app with `bun test <dir>`. In `recruiter-app`, run
**directory slices**. A bare `bun test` is known to hang.

Linux users can give the voice agent host networking for a better media path:

```bash
docker compose -f docker-compose.yml -f docker-compose.linux.yml up -d
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
