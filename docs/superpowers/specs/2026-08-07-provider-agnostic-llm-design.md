# Provider-agnostic LLM access via a LiteLLM gateway

Status: approved 2026-08-07. Supersedes nothing.

## Problem

Every text-generation path in OpenRecruiting is bound to Anthropic, through five
separate client implementations that share no code:

| Surface | Binding | Call sites |
|---|---|---|
| `backend` | injected `AsyncAnthropic` from `app/dependencies.py:221` | 11 `messages.create` + 1 streaming wrapper |
| `intake-core` | `anthropic>=0.40,<1.0`, injected client | 1, plus the tool schemas everything else reuses |
| `workers/intake-context-builder` | own `src/clients/anthropic.py` | 2 |
| `workers/feedback-agent` | hand-rolled httpx client posting to `api.anthropic.com/v1/messages` | its own module |
| `workers/intake-agent` | hand-rolled httpx client posting to `api.anthropic.com/v1/messages` (`src/clients/anthropic.py:14`) | `pipeline.py:100`, `pipeline.py:120`, via `call_haiku`/`call_sonnet` |
| `voice-agent` | `pipecat-ai[anthropic]` `AnthropicLLMService`, plus a raw `AsyncAnthropic` | `pipeline/services.py:39`, `main.py:2172` |

`workers/intake-agent` was missed by the first revision of this spec. It is
architecturally identical to `feedback-agent`'s client — the same hand-rolled httpx
POST, the same haiku/sonnet switch at `src/clients/anthropic.py:41-43`, the same
retry loop — it is a running service (`docker-compose.yml:183`) and a `depends_on`
of `backend`. It is **six** surfaces, not five.

The consequence is that a model cannot be changed without a code change, and no
non-Anthropic model can be evaluated at all. The immediate goal is to run the system
against a locally served Gemma; the durable goal is that provider choice becomes
configuration.

## Decisions

Settled during brainstorming on 2026-08-07:

1. **Scope**: all six Anthropic-coupled surfaces in one effort.
2. **Client shape**: call sites move to the OpenAI-shaped request/response LiteLLM
   speaks natively. No Anthropic-shaped compatibility facade.
3. **Tool fallback**: when a model lacks native function calling, the shared client
   emulates it with a JSON-schema prompt and validates the reply. Detected
   automatically; call sites see one shape either way.
4. **Local model**: Ollama.
5. **Deployment**: LiteLLM runs as a **proxy container**, not an in-process SDK. This
   is the only option that also covers pipecat, and it keeps provider configuration
   in one file instead of six.
6. **Shared code home**: a new `llm-core` package (see Risks for why not `intake_core`).
7. **Voice prompt caching**: its loss is accepted rather than blocking the migration.

## Architecture

A `litellm` container becomes the single egress point for text generation. No
application imports a provider SDK.

```
backend                ┐
intake-context-builder ┤
feedback-agent         ┤──►  litellm:4000  ──►  anthropic / ollama(gemma) / openai / …
intake-agent           ┤
voice-agent (pipecat)  ┘            │
                                    └── litellm-config.yaml: aliases, keys, fallbacks
```

Switching a workload to Gemma is an edit to `litellm-config.yaml` and a proxy
restart. No application rebuild, no redeploy. That property is the deliverable.

### Why a proxy rather than the SDK

`voice-agent` drives its conversation through pipecat, which needs an LLM *service
class*, not a callable. `litellm.acompletion` cannot be injected into it. Pipecat's
`OpenAILLMService` accepts a `base_url`, so an OpenAI-compatible HTTP endpoint is the
only abstraction that spans pipecat and the other four services at once. Choosing the
SDK would have left voice-agent permanently outside the abstraction, and provider
config duplicated in two places.

## Components

### `llm-core` (new shared package)

Mirrors the existing `intake-core` pattern exactly: a sibling directory installed by
`pip install` from the repo-root build context, as `backend/Dockerfile:14` and
`workers/intake-context-builder/Dockerfile:13` already do.

Public surface:

```python
from llm_core import llm

reply = await llm.complete(
    model="intake-jd",                    # an alias, not a provider model id
    messages=[{"role": "user", "content": prompt}],
    tools=[JD_TOOL],                      # OpenAI function shape
)
reply.text          # str            — normalized
reply.tool_calls    # list[ToolCall] — normalized, native or emulated
reply.finish_reason # str
```

```python
async for kind, payload in llm.stream_turn(model=..., system=..., messages=..., tools=...):
    ...  # ('text', str) | ('tool_call', dict) | ('done', {...})
```

Call sites never touch `choices[0].message.content`. Normalization lives in one file,
so a future move off LiteLLM is a single-file change.

The package also ships a `fake_llm` pytest fixture, so tests never again encode a
vendor's response shape.

### Model aliases

The twelve `*_MODEL` settings in `backend/app/config.py` stop holding provider model
IDs and start holding aliases:

| Setting | Was | Becomes |
|---|---|---|
| `INTAKE_JD_MODEL` | `claude-haiku-4-5-20251001` | `intake-jd` |
| `DEBRIEF_CHAT_MODEL` | `claude-sonnet-4-6` | `debrief-chat` |
| `SCREENING_GENERATOR_MODEL` | `claude-sonnet-4-6` | `screening-generator` |
| … | … | … |

`litellm-config.yaml` maps each alias to a provider:

```yaml
model_list:
  - model_name: intake-jd
    litellm_params:
      model: anthropic/claude-haiku-4-5-20251001
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info:
      supports_function_calling: true

  - model_name: intake-jd-local      # distinct alias, not a second entry
    litellm_params:
      model: ollama/gemma3
      api_base: os.environ/OLLAMA_API_BASE
    model_info:
      supports_function_calling: false
```

Local variants **must** use a distinct alias. Two `model_list` entries sharing one
`model_name` is not an override in LiteLLM — it declares a load-balancing group, and
requests would silently round-robin between Claude and Gemma. To run a site on Gemma,
either point its `*_MODEL` setting at `intake-jd-local`, or edit the `litellm_params`
of the existing alias in place. Never duplicate the name.

Per-call-site routing already works because each purpose has its own setting. Pointing
only JD parsing at Gemma while debrief stays on Claude requires no code.

### Tool calling and the Gemma fallback

At startup the client reads the proxy's `/model/info` and caches, per alias, whether
function calling is supported. `LLM_FORCE_JSON_TOOLS` (comma-separated aliases)
overrides the answer when the proxy cannot report it.

For a tool-using call to a model without native support:

1. Render the tool's JSON schema into the system prompt as an instruction to reply
   with conforming JSON.
2. Request `response_format={"type": "json_object"}`.
3. Validate the reply against the schema; on success synthesize a `ToolCall`
   identical in shape to a native one. On validation failure, retry once, then raise
   `ToolEmulationError`.

Callers are unaffected. Streaming with emulated tools yields the tool call at the end
of the turn rather than mid-stream, which the existing tagged contract already allows
— tool calls are emitted only once fully assembled.

### Streaming

`backend/app/services/intake/anthropic_stream.py` is rewritten internally to consume
OpenAI-shaped deltas (`choices[0].delta.content`, incremental
`tool_calls[].function.arguments`) and renamed to `llm_stream.py`. Its tagged event
contract is unchanged. The file already performs the normalization this design
depends on; only its input format changes.

**`text_runner` is NOT untouched.** Earlier revisions of this spec claimed the
unchanged tagged contract left `backend/app/services/intake/text_runner.py` alone.
That is false, and it is the most expensive error phase 1 found. `text_runner.py`
must be **rewritten** in phase 3, not wrapped, for three independent reasons:

1. `:290` is `if final_stop_reason != "tool_use": break`. `stream_turn` passes the
   provider's `finish_reason` through untouched, so an OpenAI-shaped stream emits
   `"tool_calls"`. The comparison fails on the first tool-using turn and the loop
   exits silently after one iteration — no error, no tool ever executed.
2. `:280-286` appends Anthropic `{"type": "tool_use", "id", "name", "input"}` blocks
   to `messages` *before* that check runs. Even a corrected stop-reason comparison
   leaves phantom Anthropic-shaped blocks in the history the next request replays.
3. `:274-288` and `:318-342` construct **request** history in Anthropic content-block
   form — `{"type": "tool_result", "tool_use_id": ...}` entries inside a
   `{"role": "user"}` message (`:342`). OpenAI's Chat Completions schema cannot
   accept that; tool results belong in `{"role": "tool", "tool_call_id": ...}`
   messages.

Reason 3 is why a wrapper cannot rescue this. A shim sitting between `stream_turn`
and `text_runner` only ever sees *events flowing out*; it never sees `messages`
being built inside `text_runner`. Translating the response side while the request
side still emits Anthropic content blocks fixes nothing. Phase 3 rewrites the loop
and its history construction together, and rewrites its tests with it.

## Per-service migration

| Service | Change |
|---|---|
| `backend` | Delete `get_anthropic_async_client` (`dependencies.py:211-227`). Rewrite 11 call sites to `llm.complete`. Rewrite the streaming wrapper. Translate tool schemas from `input_schema` to `function.parameters`. |
| `intake-core` | Drop the `anthropic` dependency. `coverage_tracker.py:81` moves to `llm.complete`; `tools/schemas.py` and `screening/tools.py` emit OpenAI tool shape. |
| `workers/intake-context-builder` | Delete `src/clients/anthropic.py`. `parse_jd.py:24` and `synthesize.py:65` move to `llm.complete`; both stop reading `response.content[0].text`. |
| `workers/feedback-agent` | Repoint the existing httpx client at the proxy with an OpenAI-shaped payload. `call_haiku` → `feedback-haiku`, `call_sonnet` → `feedback-sonnet`. |
| `workers/intake-agent` | Same change as `feedback-agent`, on a near-identical file. `src/clients/anthropic.py:41-43` stops choosing a model id; `call_haiku` → `intake-agent-haiku`, `call_sonnet` → `intake-agent-sonnet`. |
| `voice-agent` | `pipeline/services.py:39` swaps `AnthropicLLMService` for `OpenAILLMService(base_url=...)`. The raw `AsyncAnthropic` at `main.py:2172` migrates with the coverage tracker. |

## Configuration

New environment variables:

| Variable | Purpose |
|---|---|
| `LLM_GATEWAY_URL` | `http://litellm:4000` in compose |
| `LITELLM_MASTER_KEY` | proxy auth; apps send it as their API key |
| `LLM_FORCE_JSON_TOOLS` | optional alias list forced onto emulated tool calling |
| `OLLAMA_API_BASE` | `http://host.docker.internal:11434` |

`ANTHROPIC_API_KEY` stops being read by application containers and is consumed only by
the proxy. `.env.example` and `docs/setup/` are updated to match, since a setup doc
that names variables the code no longer reads has already caused a setup-blocking bug
on this project once.

## Error handling

- Provider errors surface as `LLMError` with the alias, upstream status, and provider
  name attached — never a bare empty-string message.
- Timeouts default to 60s and are configurable per alias in the proxy config.
- Retries are the proxy's responsibility (`num_retries`), not each app's, so behaviour
  is uniform and tunable without redeploys.
- Fallback chains are declared in proxy config, letting a local-model failure fall back
  to Claude during evaluation.

## Testing

29 test files reference the Anthropic client or its response shape and must be
rewritten. There is no shared fixture, so they are independent and can be migrated in
parallel: `backend/tests` (17), `workers/intake-context-builder/tests` (5),
`intake-core/tests` (2), `voice-agent/tests` (2), `workers/intake-agent/tests` (3 —
`test_pipeline.py`, `test_handler_warm.py`, `test_screenable_flag.py`, all of which
stub `AnthropicClient`). `workers/feedback-agent/tests` has none, because that client
is hand-rolled and its tests mock httpx instead.

The `fake_llm` fixture from `llm-core` replaces per-file mocks.

Acceptance:

1. All five suites green against Claude aliases, at their current counts — backend
   2105, cortex-backend 486, recruiter-app 1224, landing 31, cortex-mcp 152.
2. `make verify` unchanged, plus a new row asserting the proxy is reachable.
3. A documented `make verify-local-llm` flips aliases to `ollama/gemma3` and exercises
   one non-tool site (JD parse) and one tool-using site end to end, proving both the
   native and emulated paths.

## Rollout

Seven phases, each independently shippable with suites green:

1. `litellm` container, `litellm-config.yaml`, `llm-core` package with `fake_llm`.
2. `backend` non-streaming call sites (11).
3. `backend` streaming: `anthropic_stream.py` → `llm_stream.py`, **plus the rewrite
   of `text_runner.py` and `debrief_chat/runner.py`** (see Streaming above).
4. `intake-core` and `intake-context-builder`.
5. `feedback-agent`.
6. `intake-agent` — same shape as phase 5, on the surface this spec first missed.
7. `voice-agent`.

## Risks

**Emulated tool calling is weaker than native.** JSON-schema emulation on Gemma will be
materially less reliable than Claude's native tool use, most of all for the multi-tool
debrief agent. It is sufficient to prove plumbing end to end; it is not suitable for
scoring or destructive actions. Sites where a malformed call is dangerous should be
kept on tool-capable models in config.

**Voice loses prompt caching.** `enable_prompt_caching=True` at
`voice-agent/src/pipeline/services.py:43` is Anthropic-specific and does not survive
the swap to `OpenAILLMService`. Expect higher token spend and somewhat higher
first-token latency. Accepted rather than blocking; worth measuring after phase 7.

**Voice gains a network hop.** It is the only realtime path. If added latency proves
unacceptable, voice-agent can point at Ollama or Anthropic directly while keeping the
same OpenAI-shaped service class — the abstraction survives, only the URL changes.

**A new package over folding into `intake_core`.** `intake_core` is already installed
into three services, so reusing it would have cost nothing. It was rejected because
debrief, screening, and feedback would then import an intake-named package for
unrelated work. The price is three additional Dockerfile edits.

**Tool schema translation is mechanical but wide.** Twelve sites use tool calling;
`input_schema` → `function.parameters` must be applied consistently or calls fail at
runtime rather than at import.

## Non-goals

- `cortex-backend` and its OpenAI embeddings. Changing an embedding model invalidates
  every vector already in Neo4j and needs its own change with a reindex plan.
- Deepgram, TTS, and transcription.
- Any change to prompt text.
