---
name: setup-openrecruiting
description: Use when the user wants to set up, configure, install or troubleshoot a self-hosted OpenRecruiting instance — including "help me set this up", "why isn't the bot joining", "no feedback is coming back", "configure my keys", or any first run from a fresh clone. Walks the setup wiki, writes .env, verifies each step, and diagnoses failures.
---

# Setting up OpenRecruiting

Get the user from a fresh clone to an instance that can run a real interview:
AI intake, a bot that joins the call, a transcript, AI feedback.

## Division of labour

You **cannot** create accounts, buy domains, or click through third-party
dashboards. Do not pretend otherwise and do not try to drive a browser to do it.

| You do | They do |
|---|---|
| Read repo state, decide what is already configured | Create the seven accounts |
| Ask for one credential at a time, in order | Buy/attach a domain |
| Write `.env`, run `docker compose` | Create the tunnel and TURN key in Cloudflare |
| Run every verification command | Register Recall webhooks |
| Read logs and diagnose failures | Paste `schema.sql` into Supabase's SQL editor |
| Run `staff_user.sql` guidance | Copy credentials back to you |

## Before anything else

1. **Read the wiki. Do not work from memory.** `setup-wiki-docs/README.md` is
   the spine; the sibling pages carry the detail and each ends with a
   verification command. If the wiki and this skill disagree, the wiki wins —
   it is maintained alongside the code.

2. **Find out where they already are.** Never start from step 1 without
   checking; most people arrive mid-way or with something broken.

```bash
test -f .env && echo ".env exists" || echo "no .env yet"
docker compose ps --format '{{.Service}}\t{{.State}}' 2>/dev/null | head -20
```

3. **Read the readiness state**, which is the fastest description of what is
   configured. It is a pure function of `.env`, so you can call it directly
   without the setup UI running:

```bash
cd setup-ui && python3 -c "
import sys; sys.path.insert(0,'.')
from app.envfile import parse
from app.readiness import evaluate
vals = parse(open('../.env', encoding='utf-8').read())
for f in evaluate(vals):
    tag = 'REQUIRED' if f.required else 'optional'
    print(f'{f.state:8} {tag:9} {f.name:20}', ', '.join(f.missing))
"
```

Report what is already `live` before asking for anything. Asking for a key they
have already configured destroys confidence in the rest of the process.

## The order, and why it is not negotiable

Follow `setup-wiki-docs/README.md`. Two orderings trip people up:

- **Cloudflare before Recall.** Recall's webhooks are registered against a
  hostname, and creating the tunnel is what produces it. The tunnel does not
  need to be serving traffic yet.
- **Schema after the Supabase keys, before the apps are useful.** The setup UI
  cannot report on the schema until the keys are in. Sequence: keys → UI says
  "not applied" → they paste `schema.sql` → re-check.

## Collecting credentials

Ask for **one at a time**, and say what it unlocks. A wall of seven requests
gets a wall of half-answers.

For each, name the exact dashboard path from the relevant wiki page rather than
a vague "get your API key".

Never echo a secret back in full. Confirm with the last four characters.

## Writing configuration

`.env` is the source of truth and the setup UI is a front end to it. Either is
legitimate; prefer whichever the user is already using.

**Back up before editing:**

```bash
cp .env ".env.bak-$(date +%s)"
```

**A restart does not apply an `.env` change.** Compose reads `env_file` at
container *create* time, so the value must be applied by recreating:

```bash
docker compose up -d --no-build <service>
```

Use `setup-ui/app/varmap.py` to find which services read a given variable — a
change applied to the wrong set looks saved and does nothing. Some variables are
read by more than one service.

## Verify every step before moving on

Never say a step worked without running its check. Each wiki page ends with one.
The most useful:

```bash
# Stack health and URL map
make verify

# Backend up
curl -s http://localhost:8004/health          # {"status":"healthy",...}

# Model gateway authenticated
KEY=$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2-)
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $KEY" \
  http://localhost:4000/model/info            # 200

# Public tunnel reaches the backend (substitute their hostname)
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://HOST/api/v2/webhooks/recall/bot-status \
  -H 'Content-Type: application/json' -d '{}'  # 401 is HEALTHY: signature check is on
```

A `401` from the webhook endpoint is the *correct* answer. Do not "fix" it.

## Diagnosing

Check readiness first — it explains most failures faster than logs do. Then:

```bash
docker compose logs --tail=50 <service>
```

Failures that do not look like configuration problems:

| Symptom | Cause |
|---|---|
| Bot joins, no transcript or feedback ever appears | `RECALL_WEBHOOK_SECRET` unset/mismatched, or the tunnel is not reaching you |
| AI feedback never returns, no error anywhere | `LAMBDA_CALLBACK_SECRET` unset — the backend rejects every worker callback. Both `backend` and `feedback-agent` need it |
| Bot joins and stays silent, browser voice fine | TURN. Either the Cloudflare pair or the static trio, not neither |
| Voice connects, transcribes nothing | `DEEPGRAM_API_KEY` |
| Invited user never receives anything | Email provider unset — no error is raised, the send is never attempted |
| "Sign-in is temporarily unavailable" on Google | `BACKEND_INTERNAL_URL` must be a container address (`http://backend:8004`), not a `NEXT_PUBLIC_` browser URL |
| Every AI action fails, containers healthy | The gateway holds the keys — check `docker compose logs litellm` |
| Saved a setting, nothing changed | It was restarted, not recreated — or applied to the wrong services |

## Things not to do

- **Do not invent a verification result.** Run the command and read it.
- **Do not ask for the Supabase database password.** The setup UI deliberately
  never collects it. Applying the schema is the user's job in the SQL editor.
- **Do not re-run `schema.sql` to "fix" an error.** It is guarded and will
  refuse. A failed apply already rolled back completely, so the fix is to
  address the cause and run it once.
- **Do not tell the user a feature is optional** unless it is one of: Google
  sign-in, model choice, the Cortex MCP connector, ATS sync, the knowledge
  graph. Everything else is needed to run a real session.
- **Do not commit `.env`** or paste secrets into anything you write.

## Finishing

Setup is not done when the containers are healthy. It is done when a real
session works — step 8 of the spine. Walk them through it and confirm a
transcript and feedback actually appear.

Then report honestly: what is live, what is still not configured, and what each
gap costs them.
