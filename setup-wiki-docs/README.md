# Setting up OpenRecruiting

This is the full path from a fresh clone to a working instance that can run a
real interview: AI intake, a bot that joins the call, a transcript, and
AI-generated feedback.

Budget **90 minutes**. Most of it is creating accounts, not configuring
software.

Each step links to a page that walks it in detail. Do them in order — several
depend on values produced by an earlier one.

---

## What you'll need

Seven accounts. **None of these are optional.** The stack will start without
them, but you cannot run a meaningful session:

| Service | What it does | Cost to start |
|---|---|---|
| [Supabase](supabase.md) | database and sign-in | free tier |
| [Anthropic](ai-keys.md) | AI intake, feedback, screening | pay as you go |
| [Deepgram](ai-keys.md) | speech-to-text for voice | free credit |
| [Recall.ai](recall.md) | the bot that joins and records | paid |
| [Cloudflare](cloudflare.md) | a domain, a tunnel, a TURN relay | domain is paid; tunnel and TURN free |
| [Resend](email.md) | invitations, feedback links, password resets | free tier |

Genuinely optional, and skippable on a first pass: [Google
sign-in](google-auth.md), changing which model each workload uses,
and the Cortex MCP connector.

You also need **Docker** with Compose, and a domain you control.

### Why a domain is not negotiable

Recall.ai runs in its own cloud and **calls your instance** when a recording
finishes. Without a public address it can join meetings and record them, but the
result never reaches you — no transcript, no feedback. A Cloudflare tunnel gives
you that address without opening a port.

The bot's audio is a second, separate problem: media is UDP, which no HTTP
tunnel carries. That is what the TURN relay is for.

---

## 1. Create the accounts and collect credentials

Work through these and keep every value in a scratch file. Nothing is entered
anywhere yet.

| | Page | You end up with |
|---|---|---|
| 1a | [Supabase](supabase.md#1-create-the-project) | project URL, publishable key, secret key, JWT secret |
| 1b | [AI keys](ai-keys.md) | Anthropic key, Deepgram key |
| 1c | [Cloudflare](cloudflare.md) | tunnel token, public hostname, TURN token id + API token |
| 1d | [Recall](recall.md) | API key, webhook signing secret |
| 1e | [Email](email.md) | Resend API key, a verified from-address |

**Do Cloudflare before Recall.** Recall's webhooks are registered against your
public hostname, and creating the tunnel is what gives you that hostname. It
does not need to be serving traffic yet — it starts carrying requests at step 3.

---

## 2. Start the stack

```bash
git clone https://github.com/Nit-1997/OpenRecruiting.git && cd OpenRecruiting
cp .env.example .env
docker compose up -d --build
```

First build pulls a lot; expect several minutes.

**Verify** — every service should report a state:

```bash
make verify
```

Services will be running but unconfigured. That is expected: nothing has keys yet.

---

## 3. Enter your settings

Open **<http://127.0.0.1:3010>** — the setup UI. Choose a password on first
visit.

It binds to `127.0.0.1` only, because it can edit every secret and restart
containers. On a remote host, tunnel to it: `ssh -L 3010:localhost:3010 user@host`.

Fill in **Get started** first — Supabase, Anthropic, Deepgram, Recall — then
**Domains** for the tunnel token and public address, and **Voice** for TURN.
Press **Review & apply**. The UI writes `.env` and recreates only the services
each change affects.

### Secrets you generate yourself

Four settings are not credentials from anyone — they are shared secrets this
stack uses to talk to itself. Two ship **blank** and break things quietly if you
leave them:

| Setting | Where | If left blank |
|---|---|---|
| `LITELLM_MASTER_KEY` | AI models | Nothing can reach the model gateway. |
| `LAMBDA_CALLBACK_SECRET` | Integrations | The backend rejects every background-worker callback, so **AI feedback never comes back**. Nothing reports an error. |
| `INTERNAL_API_SECRET` | Advanced | Defaults to `change-me-local-only`. Change it. |
| `CORTEX_INTERNAL_SECRET` | Knowledge graph | Same default. Change it. |

Any long random string works. Generate four:

```bash
for i in 1 2 3 4; do openssl rand -hex 32; done
```

**Verify** — the **What works** panel should show your required features moving
to `live`. Anything still `not set up` names the variables it is waiting for.

Two will still be incomplete, and that is expected at this point:

- **Core** — needs the database, which is step 4.
- **Email** — step 5.

---

## 4. Create the database schema

The setup UI cannot do this one for you. Supabase's service key can read your
data but cannot run DDL; applying a schema needs the database password, which
this UI deliberately never asks for.

In the Supabase dashboard: **SQL Editor → New query**, paste the entire contents
of [`schema.sql`](../schema.sql), and **Run**.

It runs as a single transaction, so it either lands completely or changes
nothing. If you run it twice it refuses with a plain message rather than
half-applying.

**Verify** — back on `:3010`, press **Re-check** on the Database schema card. It
should turn `ready`.

Full detail, including the optional demo data: [Supabase
setup](supabase.md#2-apply-the-schema).

---

## 5. Turn on email

Add your Resend key and from-address in the setup UI's **Email** group, and set
the provider to `resend`.

Without this, no interview invitation, feedback link or password reset is ever
sent — and nothing surfaces an error, because the send is never attempted.

**Verify** — the readiness panel shows Email as `live`.

Detail: [Email setup](email.md).

---

## 6. Create your staff account

Staff can see every organization in the instance and set their credit budgets.

Edit the CONFIG block at the top of [`staff_user.sql`](../staff_user.sql) with your
email and a password, then run it in the Supabase SQL editor. It creates the auth
user, a confirmed email identity, and the staff profile together, and is safe to
re-run.

**Verify** — sign in at **<http://localhost:3001>**. You should reach the admin
portal, not a redirect back to login.

---

## 7. Create your first organization

In the admin portal:

1. **New Organization** — name it.
2. Open it. It starts with **10 intake and 10 interview credits**; change the
   budget with the pencil on the Credit Budget card.
3. Add a user by email. They receive a magic link.

Credits are per organization, shared by everyone in it. One intake session or one
recorded interview consumes one.

**Verify** — the invited user can sign in at **<http://localhost:3005>**.

---

## 8. Run a real session

Nothing before this proves the product works. This is the acceptance test.

1. Sign in to the recruiter app at `http://localhost:3005`.
2. Create a requisition and complete **AI intake** — this consumes an intake
   credit and exercises Anthropic through the gateway.
3. Add a candidate and schedule an interview with a real meeting URL.
4. Join the meeting yourself. **The bot should join too.**
5. Talk for a minute or two, then leave.
6. Within a few minutes the round should carry a **transcript**, and AI feedback
   should appear.

If the bot joins but nothing comes back, the webhook is not reaching you —
that is step 1c/1d, and [Recall
troubleshooting](recall.md#troubleshooting) covers it.

---

## When something is wrong

**Start at `:3010`.** The readiness panel tells you which features are live and
which variables each unfinished one still needs. That is faster than reading
logs.

Then:

```bash
make verify                          # per-service health and the URL map
docker compose logs -f backend       # or any service name
```

Each provider page ends with its own troubleshooting section for the failures
actually seen in practice.

## Where things run

| | |
|---|---|
| `landing` :3000 | sign-in |
| `recruiter-app` :3005 | the dashboard |
| `admin-app` :3001 | staff portal |
| `setup-ui` :3010 | configuration (localhost only) |
| `backend` :8004 | the API |
| `voice-frontend` :3003, `voice-agent` :8011 | voice calls |
| `cortex-backend` :8010, `cortex-mcp` :8020, `neo4j` :7474 | knowledge graph |
| `litellm` :4000 | the model gateway |

Publicly, everything is served through **one hostname**, path-routed by Caddy
through the tunnel — not four subdomains. `/api/*` reaches the backend,
`/voice-ws-v2/*` the voice agent, `/mcp` the connector, and everything else the
voice frontend.
