# Recall.ai setup

Recall.ai runs the meeting bots that join interviews, record them, and produce
transcripts. **It is required.** The stack starts without it, but no interview is
ever captured and no AI feedback is ever generated — which is most of what this
platform is for.

It is also the one dependency that has to reach *you*. Recall is a cloud service
that calls your backend over webhooks, so your backend needs a URL Recall can
resolve from the internet. That is what the Cloudflare tunnel is for — set it up
first: [Cloudflare setup](cloudflare.md).

## 1. Get an API key

Create an account at <https://recall.ai> and copy your API key.

In the setup UI at **<http://127.0.0.1:3010>**, paste it into **Get started →
Recall API key**.

Check your account's region while you are there. **Meeting capture → Recall API
base URL** defaults to `us-west-2`; if your account lives elsewhere, change it or
every call returns 401.

## 2. Leave the bot name alone (unless you read this)

```bash
RECALL_BOT_NAME=Scout
```

This is the display name the bot joins under, and it is **load-bearing**. The
transcript pipeline filters out the bot's own utterances by matching this name;
if it stops matching, the bot's speech gets scored as interviewer feedback and
AI feedback fires on interviews where no human said anything.

The guard is in code, not config, precisely so the two cannot drift:

- `backend/app/services/recall_webhook/constants.py` → `BOT_SPEAKER_NAMES`
- `workers/feedback-agent/src/clients/supabase.py` → `_BOT_SPEAKER_NAMES`

The backend **refuses to start** if `RECALL_BOT_NAME` is not in that set. So if
you rename the bot, add the lowercased name to both files.

## 3. Expose your backend publicly

Follow [Cloudflare setup](cloudflare.md) first. It gives you a permanent
hostname served through the bundled `cloudflared` container, with Caddy
path-routing `/api/*` to the backend.

Set that hostname once, as **Public address** under **Get started** in the setup
UI at `:3010`. It expands into the eight variables that need it, including
`WEBHOOK_BASE_URL`.

> An ad-hoc tunnel — `ngrok http 8004`, or `cloudflared tunnel --url` — will
> carry webhooks, but gives you a *new* hostname every restart and none of the
> path routing the frontends expect for voice and MCP. Fine for a quick test,
> wrong for a real install.

## 4. Register the webhooks

In the Recall dashboard, add these endpoints (both, they carry different events):

| Endpoint | Purpose |
|---|---|
| `<WEBHOOK_BASE_URL>/api/v2/webhooks/recall/bot-status` | bot lifecycle: joining, recording, done, failed |
| `<WEBHOOK_BASE_URL>/api/v2/webhooks/recall/realtime` | live transcript, participant join/leave, chat |

Set a signing secret in the Recall dashboard, then paste the same value into
**Get started → Recall webhook secret** in the setup UI and press **Review &
apply**. It restarts the backend for you.

## 5. Check it

An unsigned request must be rejected. This is the healthy answer:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://localhost:8004/api/v2/webhooks/recall/bot-status \
  -H 'Content-Type: application/json' -d '{}'
# 401
```

A `401` means signature verification is on and working. A `404` means the
backend is not running. Recall's dashboard has a "send test event" button that
exercises the signed path properly.

## What happens without a tunnel

The rest of the app keeps working — requisitions, AI intake, candidates and
rounds, browser voice. What you lose is the callback: bots join and record, but
the "recording finished" event never reaches you, so transcripts never land and
AI interview feedback never triggers.

That is not a usable install, which is why the tunnel is required rather than
recommended. If you are mid-setup and want to exercise the feedback pipeline
before the tunnel is up, you can submit interviewer feedback by hand through the
feedback portal.

## Troubleshooting

**Every webhook returns 401.** The signing secret in the setup UI does not match
the one in the Recall dashboard, or the value was saved but never applied — press
**Review & apply**, which is what actually recreates the backend.

**Bots never join.** Check `RECALL_API_KEY` and that `RECALL_BASE_URL` matches
your account's region.

**Bots join but nothing comes back.** Your public address is not reachable from
the internet. Check the tunnel is connected, and that the hostname registered in
Recall's dashboard is the one your tunnel actually serves:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST https://<your-hostname>/api/v2/webhooks/recall/bot-status \
  -H 'Content-Type: application/json' -d '{}'
# 401
```

Anything other than `401` means Recall cannot reach you either. See
[Cloudflare troubleshooting](cloudflare.md#troubleshooting). If you used an
ad-hoc tunnel, note that restarting it issues a *new* hostname and the one in
Recall's dashboard is now dead.

**The bot's own words show up as interviewer feedback.** `RECALL_BOT_NAME` and
the speaker-name sets have drifted apart. See step 2.
