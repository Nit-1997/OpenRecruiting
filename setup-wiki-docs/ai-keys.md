# AI provider keys

Two required keys — **Anthropic** and **Deepgram** — and one optional
(**OpenAI**). Five minutes.

## What this gets you

Anthropic drives every language task: AI intake calls, interview feedback,
screening questions, résumé extraction. Deepgram turns speech into text, which
is what makes the voice agent and the interview transcript work.

## Where the keys live

Provider keys are held **only by the LiteLLM gateway**, never by an application
container. Each workload asks for a model by alias — `intake`, `feedback`,
`screening` — and the gateway decides which provider serves it. That is what
makes swapping models a config change rather than a code change.

Deepgram is the exception: speech-to-text does not go through the gateway, so
the voice agent reads that key directly.

---

## 1. Anthropic — required

Create an account at <https://console.anthropic.com>, add credit, then
**API Keys → Create Key**.

Set it in the setup UI under **Get started → Anthropic API key**.

This is the default behind every model alias. Without it nothing that thinks
works: intake produces no questions, no feedback is generated, screening cannot
run.

## 2. Deepgram — required

Create an account at <https://deepgram.com>. New accounts come with free credit.
**API Keys → Create a New API Key.**

Set it under **Get started → Deepgram API key**.

Without it the voice agent starts and accepts a call, then transcribes nothing —
so an AI intake call connects and goes nowhere.

## 3. OpenAI — optional

Only needed for the knowledge graph, which uses OpenAI for embeddings. Set it
under **Get started → OpenAI API key** if you want Cortex to answer questions
about your data.

Everything else runs on Anthropic.

## 4. Choosing models — optional

**Models per task** in the setup UI lists every workload and what each currently
resolves to. Change one without touching the others.

The defaults are sensible. Come back to this when you have a reason — a cheaper
model for high-volume screening, a stronger one for feedback.

## Verify

The readiness panel on `:3010` shows **Core** and **Browser voice** as `live`.

To check the gateway is actually serving your key — this reads `.env` rather than
setting it, so it is safe to run at any time:

```bash
KEY=$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2-)
curl -s -H "Authorization: Bearer $KEY" http://localhost:4000/model/info | head -c 200
```

A JSON list of models means the gateway is up and authenticated. `401` means
`LITELLM_MASTER_KEY` disagrees between the gateway and the services.

`make verify` prints a friendlier version of the same check.

## What breaks without them

| Missing | Consequence |
|---|---|
| Anthropic | No intake questions, no interview feedback, no screening. The apps load and every AI action fails. |
| Deepgram | Voice calls connect but transcribe nothing. Interview transcripts never appear. |
| OpenAI | No knowledge graph. Everything else is unaffected. |

## Troubleshooting

**Every AI action fails but the containers are healthy.** Check the gateway
first — it holds the keys, not the app:

```bash
docker compose logs litellm | tail -30
```

**`401` from the gateway.** `LITELLM_MASTER_KEY` is how the services authenticate
to the proxy. It must match on both sides; the setup UI writes it to both.

**Anthropic returns 400 for a model you selected.** The alias points at a model
your account cannot reach. Change it in **Models per task**.

**Voice connects, then silence.** That is Deepgram, not the model key. Check
`docker compose logs voice-agent` for a transcription error.
