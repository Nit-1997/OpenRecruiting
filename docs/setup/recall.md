# Recall.ai setup

Recall.ai runs the meeting bots that join interviews, record them, and produce
transcripts. It is entirely optional: **the platform runs fine without it**, you
just don't get automatic meeting capture or the AI interview feedback that
depends on a transcript.

It is also the one dependency that has to reach *you*. Recall is a cloud service
that calls your backend over webhooks, so your backend needs a URL Recall can
resolve from the internet. On a laptop that means a tunnel.

## 1. Get an API key

Create an account at <https://recall.ai>, copy your API key, and set it in `.env`:

```bash
RECALL_API_KEY=your-key-here
```

Check the region while you're there. `RECALL_BASE_URL` defaults to
`https://us-west-2.recall.ai/api/v1`; if your account is in another region,
change it or every call will 401.

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

Pick either:

```bash
ngrok http 8004
# or
cloudflared tunnel --url http://localhost:8004
```

Copy the resulting `https://…` URL into `.env`:

```bash
WEBHOOK_BASE_URL=https://your-tunnel-url
```

## 4. Register the webhooks

In the Recall dashboard, add these endpoints (both, they carry different events):

| Endpoint | Purpose |
|---|---|
| `<WEBHOOK_BASE_URL>/api/v2/webhooks/recall/bot-status` | bot lifecycle: joining, recording, done, failed |
| `<WEBHOOK_BASE_URL>/api/v2/webhooks/recall/realtime` | live transcript, participant join/leave, chat |

Set a signing secret in the dashboard and put the same value in `.env`:

```bash
RECALL_WEBHOOK_SECRET=the-signing-secret
```

Then restart the backend so it picks the config up:

```bash
docker compose up -d backend
```

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

Everything else keeps working. You can create requisitions, run AI intake, manage
candidates and rounds, and use the voice agent. What you lose is the callback:
bots will join and record, but the "recording finished" event never reaches you,
so transcripts never land and AI interview feedback never triggers.

If that's your situation, you can still exercise the feedback pipeline by
submitting interviewer feedback through the feedback portal instead.

## Troubleshooting

**Every webhook returns 401.** The signing secret in `.env` does not match the
one in the Recall dashboard, or the backend was not restarted after you set it.

**Bots never join.** Check `RECALL_API_KEY` and that `RECALL_BASE_URL` matches
your account's region.

**Bots join but nothing comes back.** Your `WEBHOOK_BASE_URL` is not reachable
from the internet — a restarted ngrok gives you a *new* URL, and the old one in
the dashboard is now dead.

**The bot's own words show up as interviewer feedback.** `RECALL_BOT_NAME` and
the speaker-name sets have drifted apart. See step 2.
