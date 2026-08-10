# Backend Streaming LLM Migration Implementation Plan (Phase 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the backend's two streaming agent loops onto `llm_core.stream_turn`, so that after this phase no file under `backend/` imports the Anthropic SDK, no file under `backend/app` carries an Anthropic tool spec, and both loops build OpenAI-shaped request history that the gateway can actually replay.

**Architecture:** Phase 1 shipped `llm-core` with `stream_turn()` written *deliberately to the existing tagged-event contract* (`('text', str) | ('tool_call', {id,name,input}) | ('done', {text,stop_reason})`), so the event shape consumers read does not change. Phase 2 moved the nine non-streaming call sites and left the streaming path, the `anthropic` pin, and `get_anthropic_async_client` alive on purpose, pinned by `backend/tests/test_anthropic_surface.py`. This phase replaces `anthropic_stream.py` with `llm_stream.py`, **rewrites** `text_runner.py` and `debrief_chat/runner.py` (loop control *and* request-history construction, together with their tests), converts the 11 debrief tool specs from Anthropic `input_schema` to OpenAI `{"type":"function","function":{...}}`, flips two model settings to gateway aliases, migrates the coverage tracker that `text_runner` feeds (see Task 4 — it is why the deletion is not optional), and finally performs the coordinated deletion phase 2 deferred.

**Tech Stack:** Python 3.11, FastAPI, `llm-core` (`openai` async client → LiteLLM proxy), `intake-core`, pytest + pytest-asyncio (`asyncio_mode = auto`), pytest-cov, Docker Compose.

**Source spec:** `docs/superpowers/specs/2026-08-07-provider-agnostic-llm-design.md`
**Prior phases:** `docs/superpowers/plans/2026-08-07-llm-gateway-foundation.md`, `docs/superpowers/plans/2026-08-09-phase2-backend-nonstreaming.md`
**Live state:** `.superpowers/sdd/CHECKPOINT.md` — its HARD-WON FACTS are binding here.

---

## Why `text_runner.py` is rewritten and not wrapped — the spec's own reasoning

Quoted verbatim from the spec, §Streaming (lines 174-196). This is the load-bearing paragraph of the phase and every task below serves it:

> **`text_runner` is NOT untouched.** Earlier revisions of this spec claimed the unchanged tagged contract left `backend/app/services/intake/text_runner.py` alone. That is false, and it is the most expensive error phase 1 found. `text_runner.py` must be **rewritten** in phase 3, not wrapped, for three independent reasons:
>
> 1. `:290` is `if final_stop_reason != "tool_use": break`. `stream_turn` passes the provider's `finish_reason` through untouched, so an OpenAI-shaped stream emits `"tool_calls"`. The comparison fails on the first tool-using turn and the loop exits silently after one iteration — no error, no tool ever executed.
> 2. `:280-286` appends Anthropic `{"type": "tool_use", "id", "name", "input"}` blocks to `messages` *before* that check runs. Even a corrected stop-reason comparison leaves phantom Anthropic-shaped blocks in the history the next request replays.
> 3. `:274-288` and `:318-342` construct **request** history in Anthropic content-block form — `{"type": "tool_result", "tool_use_id": ...}` entries inside a `{"role": "user"}` message (`:342`). OpenAI's Chat Completions schema cannot accept that; tool results belong in `{"role": "tool", "tool_call_id": ...}` messages.
>
> Reason 3 is why a wrapper cannot rescue this. A shim sitting between `stream_turn` and `text_runner` only ever sees *events flowing out*; it never sees `messages` being built inside `text_runner`. Translating the response side while the request side still emits Anthropic content blocks fixes nothing. Phase 3 rewrites the loop and its history construction together, and rewrites its tests with it.

Phase 1's hazard list (`2026-08-07-llm-gateway-foundation.md:1960-1969`) adds the second runner, and names the line:

> **`debrief_chat/runner.py` has the same silent blocker, and it degrades differently (phase 3).** `backend/app/services/debrief_chat/runner.py:132` is `if stop_reason != "tool_use" or not read_calls: break` — a second instance of the `"tool_use"` vs `"tool_calls"` mismatch, in a different service, missed because the review was looking at `text_runner`. It fails in a distinct way: here the `break` *precedes* history construction, so no phantom `tool_use` block is written, but the read-tool loop exits after one iteration and the debrief answers the recruiter with no data retrieved — a confidently wrong answer rather than an error.

**Verified against the source at HEAD.** `text_runner.py:290` and `debrief_chat/runner.py:132` are exactly as described. Line numbers in reason 3 are also exact: `:274-288` builds `assistant_content`, `:318-342` builds `tool_results_content` and appends it as `{"role": "user", ...}` at `:342`.

---

## Global Constraints

- Python `>=3.11`. No new runtime dependency is added; `llm-core` already arrives via the repo-root build context for `backend`. **`voice-agent/Dockerfile` gains an `llm-core` install in Task 4** — that is the only new install this plan introduces, and it is unavoidable (Task 4 explains why).
- **No provider SDK may be imported by any file this plan touches.** After Task 6, `grep -rn "from anthropic import\|^import anthropic" backend/` returns nothing and `anthropic` is gone from `backend/requirements.txt`. `backend/app/services/candidate_detection_service.py` and `backend/app/services/recall_webhook/end_state.py` still POST raw `httpx` to `api.anthropic.com` and still read `settings.ANTHROPIC_API_KEY`; they import no SDK, belong to no phase in the current rollout, and are deliberately untouched. `ANTHROPIC_API_KEY` therefore stays in `backend/tests/conftest.py` and in `.env`.
- **Acceptance bar, every task:** `make test` from the repo root, green. Pre-phase baseline is **2167 passed, 5 skipped**, under `--cov-fail-under=85` in `backend/pytest.ini`. A task may only move that number *up*, by exactly the tests it adds. No test may be deleted, none weakened, no new skip. **Two bounded exceptions, both accounted for in the arithmetic below:** Task 5 deletes `test_anthropic_stream.py` (2 tests) together with the module it tests, whose replacement was already covered by the 11 tests Task 1 added; Task 6 deletes `test_anthropic_surface.py` (6 tests) and one test in `test_dependencies_extra.py`, replacing all seven properties with a new 7-test file. No property is retired without a named replacement.
- `make test` rebuilds `backend/Dockerfile.test` itself, and `intake-core` **and** `llm-core` are baked into that image (CHECKPOINT fact #4). Tasks 2 and 4 change `intake-core`; `make test` picks that up on its own, but a running `backend` container will not — rebuild it.
- **`intake-core` has its own suite that `make test` does not run.** Tasks 2 and 4 change `intake-core/intake_core/`, so they must also run `cd intake-core && python -m pytest -q` and paste the count. There is no Dockerfile.test for intake-core; run it in a venv with `pip install -e ./intake-core`. **A task that changes intake-core without running that suite has shipped an unverified change** — 81 test functions live there and none of them are in the backend gate.
- **`voice-agent` has no test covering the code Task 4 changes.** Its verification is `docker compose up -d --build voice-agent` followed by `make verify` showing `ok voice-agent`. Say so in the commit; never claim a suite that was not run.

  **Review addendum — that is too weak on its own, and the plan already contains the fix.**
  `make verify` only proves the container answers `/health`; it would stay green with a
  coverage tracker that raises on every turn, because the tracker is spawned as a
  supervised background task whose failures are logged, not surfaced. Task 4 already
  migrates `voice-agent/scripts/smoke_test_v2.py` onto the gateway (see its Step for
  `:75-88`), so **run that script as the real verification** — it exercises
  `run_coverage_tracker` against the live gateway end to end, which is precisely the code
  path with no test. Record its output in the commit. If it cannot be run in the
  environment, say so explicitly rather than substituting `make verify` and calling the
  task verified.
- Rebuild and restart affected containers after changes: `docker compose up -d --build backend` (and `voice-agent` in Task 4). Task 3 and Task 4 also change `litellm-config.yaml`, which needs `docker compose up -d litellm` — the proxy reads that file at boot and a new alias does not exist until it restarts.
- Commit after each task with a meaningful message. **Self-review the diff before committing** (`git diff --cached`).
- Every HTML element added anywhere in this project must carry a unique `id`. (No UI is added by this plan; the rule is project-wide.)
- No API keys, secrets, certs, or `.env` files may be committed. Secrets live in the root `.env`; `.env.example` documents names with empty values only.
- Run `npm run build` before committing any change touching a Next.js app. (No app is touched. `recruiter-app` **reads** the SSE `done` payload — see "What the frontend sees" below — but its contract is unchanged, so no frontend edit is required.)
- **No prompt text changes.** A spec non-goal.

---

## The real `llm_core` streaming API — quoted, not assumed

Every signature and event shape below was read from the shipped source at HEAD, not inferred.

### `stream_turn` — the exact signature

`llm-core/llm_core/client.py:266-274`:

```python
    async def stream_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[tuple[str, Any]]:
```

All keyword-only. **No `temperature`. No `tool_choice`.** `FakeLLM.stream_turn` (`llm-core/llm_core/fake.py:216-224`) has the identical signature, and `llm-core/tests/test_fake.py` compares both with `inspect.signature`, so a test cannot pass against the fake and fail against the gateway.

### The exact events it yields

Three tags, always as a 2-tuple `(kind, payload)`:

| tag | payload | emitted at |
|---|---|---|
| `('text', str)` | one incremental content delta | `client.py:379`, once per truthy `delta.content` |
| `('tool_call', dict)` | `{"id": str \| None, "name": str, "input": dict}` | `client.py:458`, **after the stream is fully drained**, one per assembled slot |
| `('done', dict)` | `{"text": str, "stop_reason": str \| None}` | `client.py:460`, exactly once, last |

`text` in the `done` payload is `"".join(text_parts)` — the concatenation of every `text` event, nothing more.

### How tool calls arrive on the streaming path vs `complete()`

This is the difference that matters most, and it is not symmetric:

| | `complete()` | `stream_turn()` |
|---|---|---|
| carrier | `LLMReply.tool_calls: list[ToolCall]` | `('tool_call', {...})` events |
| arguments field | `ToolCall.arguments` (`types.py:17`) | `payload["input"]` — **a different key** |
| id | `ToolCall.id`, coerced: `getattr(raw, "id", None) or ""` (`client.py:520`) | `slot["id"]` **passed through raw — can be `None`** (`client.py:384, 386, 458`) |
| read safely by | `reply.tool_call_named(name)` (name-matched) | iterating events and matching on `payload["name"]` |
| timing | whole reply | only once the argument JSON is fully assembled |
| emulated alias | synthesizes a `ToolCall` from JSON (`client.py:474-482`) | **emits no `tool_call` event at all** (`client.py:320-334`) |
| malformed / truncated arguments | `arguments={}` + `llm_tool_arguments_invalid` warning (`client.py:501-511`) | `input={}` + `llm_stream_tool_json_invalid` warning (`client.py:436-449`) |
| nameless call | `LLMError` (`client.py:489`) | `LLMError` (`client.py:428`) |

Two consequences the tasks below act on: **`input`, not `arguments`**, and **`id` may be `None`**.

### `stream_turn` deliberately has no `tool_choice`, and what each site does about it

From its own docstring (`client.py:293-303`), and from `.superpowers/sdd/2026-08-09-phase2-backend-nonstreaming/tool-choice-report.md` §1:

> There is deliberately NO `tool_choice` here, though complete() has one. Two reasons, and the second is the one that decided it. First, nothing streams a forced tool call: every site that wants forcing wants a single verdict, which is complete()'s shape. Second, and worse, this method **cannot honour the promise**. On an emulated alias it yields no tool_call event at all […] so a caller who passed tool_choice and got prose would be holding a guarantee that was never true — the same silent gap between believed and actual forcing that complete()'s tool_choice exists to close.

**What each streaming site does about forcing: nothing, and nothing is needed.**

- **`text_runner`** — the intake agent is conversational. It must be free to answer in prose, and it must be free to call zero, one, or several tools per turn. Forcing a tool here would be wrong even if it were available: it would make the agent call `update_answer` on a turn where the recruiter said "hold on". The loop is driven by *whether calls arrived*, so "no call" is a first-class, correct outcome.
- **`debrief_chat/runner`** — same. The model chooses between three read tools, eight propose tools, and plain prose. `"required"` would be the only meaningful forcing here and there is no site that wants it.

Neither site passes `tool_choice` today (they pass none to `client.messages.stream`), so **nothing is being dropped**. This is not the phase-2 situation, where six sites carried a forcing guarantee that had to be translated rather than discarded. Recorded so a reviewer does not read the absence as an oversight.

### The emulated-tools path cannot support these loops at all

`client.py:312-334`:

```python
        if tools:
            validate_tool_shape(tools)
            if await self._caps.supports_tools(model):
                payload["tools"] = tools
            else:
                logger.warning("llm_stream_tools_emulated", alias=model, tools=len(tools))
                outgoing = [
                    {"role": "system", "content": build_emulation_instruction(tools)},
                    *outgoing,
                ]
```

On an alias with `supports_function_calling: false` — or one named in `LLM_FORCE_JSON_TOOLS` (`capabilities.py:56-57`) — the schema goes into a system message and **the reply is never parsed back**. There is no `parse_emulated_reply` on this path. The consequences, per site:

- **`text_runner`**: zero `tool_call` events ⇒ `update_answer` / `mark_status` never execute ⇒ **the recruiter's answers are silently never persisted**, and the emulated JSON is streamed to them verbatim as chat prose. There is no error, no failing request, and no test that would notice.
- **`debrief_chat/runner`**: zero `tool_call` events ⇒ no read tool runs and no action can ever be proposed ⇒ **a confidently wrong answer over no retrieved data**, which is exactly phase 1's hazard #2 restated.

**What this plan does about it (two guards, because neither alone is sufficient):**

1. **Runtime.** `llm_stream.stream_llm_turn` refuses the call when `tools` are supplied and the alias is in `get_settings().force_json_tools`. `LLM_FORCE_JSON_TOOLS` is the documented override (`.env.example:148` currently lists `intake-jd-local,smoke-local,gemma-local`), so this is the reachable footgun. Task 1.
2. **Static.** A test parses `litellm-config.yaml` and asserts the two streaming aliases declare `supports_function_calling: true`. This is the *other* way an alias becomes emulated, and llm-core exposes no public accessor for the capability table (`CapabilityCache` is reached only through the private `LLMClient._caps`), so it cannot be checked at runtime without either a private attribute read or a new llm-core API. Task 1.

**Carried forward, not solved here:** llm-core has no public `supports_tools(alias)`. Adding one is additive and cheap and would let both runners refuse a config-level emulated alias at runtime too. It is out of phase-3 scope because it changes `llm-core` and would require re-running that package's own suite (194 passed, 12 deselected). Record it in CHECKPOINT.

### Both runners build Anthropic-shaped REQUEST history — the exact before and after

This is the crux of "rewrite, not wrap". Neither runner's *replay* helper is a problem — `text_runner._format_turns_for_anthropic` (`:74-87`) and `DebriefChatRunner._replay_history` (`:66-75`) both emit plain `{"role": ..., "content": <str>}`, which is already valid OpenAI. **Only the in-loop history is Anthropic-shaped.**

**What they build today** (`text_runner.py:274-288` and `:302-342`; `runner.py:143-181` — identical shape):

```python
# assistant turn: a content-BLOCK LIST
{"role": "assistant", "content": [
    {"type": "text", "text": "Got it. "},
    {"type": "tool_use", "id": "toolu_1", "name": "update_answer",
     "input": {"qid": "q4_must_haves", "text": "Python"}},   # input is a DICT
]}
# tool results: blocks inside a USER message
{"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "{'ok': True}"},
]}
```

**The OpenAI/LiteLLM equivalent — four separate differences, each one fatal on its own:**

```python
# assistant turn: content is a STRING (or absent); calls live in a sibling field
{"role": "assistant",
 "content": "Got it. ",                          # omitted entirely when tool-only
 "tool_calls": [                                  # omitted entirely when empty
     {"id": "toolu_1",
      "type": "function",                         # required; not optional
      "function": {"name": "update_answer",
                   "arguments": '{"qid": "q4_must_haves", "text": "Python"}'}},
 ]}                                               # arguments is a JSON *STRING*
# tool results: ONE message per call, role "tool", NOT nested in a user message
{"role": "tool", "tool_call_id": "toolu_1", "content": "{'ok': True}"}
```

| # | difference | what happens if it is missed |
|---|---|---|
| 1 | `content` is a string, not a block list | the gateway rejects the message; a 400 mid-conversation, on turn 2 |
| 2 | tool calls move from `content` blocks to a sibling `tool_calls` array with `"type": "function"` | calls vanish from the replayed history; the model re-asks for data it already has |
| 3 | **`function.arguments` is a JSON string, not the decoded dict** the `tool_call` event handed you | schema violation at the gateway. This is the single easiest thing to get wrong, because the event payload is already a dict and passing it through *looks* right |
| 4 | one `{"role": "tool", "tool_call_id": ...}` message **per call**, replacing the single user message holding every `tool_result` block | 400, and the model loses the call↔result pairing |

A fifth, provider-specific: **every entry in an assistant message's `tool_calls` must be answered by a `role: "tool"` message with a matching `tool_call_id` before the next assistant turn.** Both rewritten loops append the assistant message and then, immediately, one tool message per call. The one place they append an assistant message carrying unanswered calls is the iteration-guard break — and no further request is made after it, so nothing replays that history.

And a sixth, introduced by `stream_turn` and absent from the Anthropic path: **`id` can be `None`** (`client.py:384/386/458` — `slot["id"]` is only set `if getattr(raw, "id", None)`). `tool_call_id` is mandatory. A `None` there is a 400 on the *following* turn, after the user has already watched text stream in. Task 1 backfills it in one place.

### Everywhere a truncated or empty tool call lands on a default that reads as a real answer

CHECKPOINT fact #3: *"a degraded LLM reply (truncated tool call → `arguments={}`) lands on a default that reads as a REAL answer. […] When migrating any call site, ask what an empty `arguments` dict does to it. Key the guard on the tool schema's required property."*

On the streaming path the degraded reply arrives as `input={}` from `client.py:436-449` (invalid JSON buffer) or `:450-457` (arguments that decode to a non-object). Every landing site, traced to its end:

| # | site | what `input={}` does today | verdict | task |
|---|---|---|---|---|
| 1 | `text_runner:307` → `ahandle_tool_call` → `intake_core.tools.__init__:60` → `ahandle_update_answer(args={})` → `_validate_args` (`update_answer.py:35-49`) | `qid=None` fails `_VALID_QIDS`, returns `{"ok": False, "error": "unknown qid: None"}` | **safe** — intake-core validates. But `text_runner:313-316` still appends it to `all_tool_calls`, which is persisted on the assistant turn, so the session transcript records a tool call that did nothing, indistinguishable from one that worked | 4 |
| 2 | `text_runner` → `ahandle_mark_status(args={})` | same validation path in `mark_status.py` | **safe**, same transcript caveat | 4 |
| 3 | `debrief runner:121-127` — a **propose** call with `input={}` | becomes `proposed_action = {"kind": "propose_record_decision", "input": {}}`, is yielded to the FE as a confirm card, **and is persisted on the assistant turn** (`:205-212`). The turn then ends. | **DANGEROUS.** This is the closest analogue to phase 2's fabricated `likely_authentic` verdict: a proposed *write action* against a real candidate, invented from a truncated reply, rendered as a confirm card and stored in history. The `/actions` endpoint would reject it (`build_proposed_action` → `summary=None` → pydantic 422/400), so the write cannot land — but a recruiter sees a confirm card for "record a hiring decision" that names nothing, and the history keeps it forever | 3 |
| 4 | `debrief runner:160-173` — a **read** call with `input={}` → `DebriefReadTools.dispatch("get_candidate_detail", {})` → `_get_candidate_detail` → `_in_packet(None)` is False | returns `{"error": "candidate not in this debrief"}`, fed back as a tool_result | **safe**, and correctly visible to the model | 3 |
| 5 | `stream_turn` raising `LLMError` on a **nameless** call (`client.py:428`) | `text_runner` does not catch it: it propagates out of `run_text_turn` into the router's `except Exception` (`intake_text_messages.py:90`) which emits an SSE `error` frame. **The user turn was already persisted at `:224`; the assistant turn never is.** The session is left with an orphan user turn | pre-existing (`anthropic_stream` could raise too), **not** introduced here; recorded so it is not mistaken for a regression | — |
| 6 | `id=None` on an otherwise valid call | see the sixth difference above — a 400 on the *next* turn | **DANGEROUS**, new on this path | 1 |
| 7 | the whole **emulated-alias** case | zero tool events; both loops complete having executed nothing | **DANGEROUS**, see above | 1 |

**The guard, applied identically at sites 1-4:** key on the tool schema's declared `required` set, exactly as phase 2 did. A call whose `input` does not contain every required property is **not dispatched**; it is logged with a distinct event name and the tool result fed back to the model names the missing properties, so the next iteration can retry. Sites 1-2 keep their intake-core validation as defence in depth; the guard exists so the failure is *named and logged* rather than arriving as `unknown qid: None`. Site 3 additionally refuses to become a `proposed_action`.

---

## Call-site inventory — 2 loops, 1 seam, 2 routers, 11 + 2 tool specs

| # | File | What changes | Anthropic shape it carries today |
|---|---|---|---|
| 1 | `backend/app/services/intake/anthropic_stream.py` | **deleted**, replaced by `llm_stream.py` | `client.messages.stream(...)`, `content_block_start` / `content_block_delta` / `content_block_stop` events, `stream.get_final_message()` |
| 2 | `backend/app/services/intake/text_runner.py` | **rewritten** — loop control `:290`, assistant history `:274-288`, tool results `:302-342`, coverage-tracker kwarg `:234-240` | `tool_use` blocks, `tool_result` in a user message, `stop_reason == "tool_use"` |
| 3 | `backend/app/services/debrief_chat/runner.py` | **rewritten** — loop control `:132`, assistant history `:143-157`, tool results `:159-181`, propose interception `:117-127` | same three |
| 4 | `backend/app/services/debrief_chat/tool_specs.py` | **11 specs** converted to OpenAI shape | `input_schema` ×11 |
| 5 | `intake-core/intake_core/tools/__init__.py` + `.../tools/schemas.py` | gains a derived OpenAI export; the Anthropic source dicts are left alone for voice-agent | `input_schema` ×2 |
| 6 | `intake-core/intake_core/coverage_tracker.py` | `messages.create` → `llm.complete`; parameter renamed | `response.content[0].text` |
| 7 | `backend/app/api/v2/routers/intake_text_messages.py` | dependency + model + kwarg rename | `get_anthropic_async_client`, `ANTHROPIC_MODEL = "claude-sonnet-4-6"` |
| 8 | `backend/app/api/v2/routers/debrief_chat.py` | `_build_runner` client swap | `get_anthropic_async_client()` — called **directly**, not via `Depends` |
| 9 | `voice-agent/src/main.py` + `scripts/smoke_test_v2.py` + `Dockerfile` | tracker client swap; forced by #6 | `from anthropic import AsyncAnthropic` at `:2172` |
| 10 | `backend/app/dependencies.py`, `backend/requirements.txt`, `backend/tests/test_anthropic_surface.py` | **the coordinated deletion** | the last `from anthropic import` in the backend |

**The debrief service carries 11 tools, not 12.** `READ_TOOL_SPECS` has 3 (`get_candidate_detail`, `get_transcript_evidence`, `get_graph_standing`); `PROPOSE_TOOL_SPECS` has 8 (`propose_add_round`, `propose_open_scheduler`, `propose_request_feedback`, `propose_record_decision`, `propose_advance_reject`, `propose_new_debrief`, `propose_quick_replies`, `propose_log_insight`). Counted from the source and cross-checked against `test_propose_tools_present`, which asserts exactly those eight names. Phase 1's hazard note and the phase-3 brief both say 12; **they are wrong**, and every count in this plan uses 11.

### Tool-spec `literal_eval`-ability — measured, not guessed

CHECKPOINT fact #6 requires proving specs were **moved, not retyped**, by parsing both versions and asserting dict equality, and notes two phase-2 specs needed `exec` because of computed enums. Measured on this phase's specs by parsing the AST at HEAD:

| symbol | `ast.literal_eval` | why |
|---|---|---|
| `debrief_chat.tool_specs.READ_TOOL_SPECS` | **OK** (3 items) | pure literals |
| `debrief_chat.tool_specs.PROPOSE_TOOL_SPECS` | **FAILS** — `ValueError: malformed node or string on line 131: Name(id='_PROPOSE_NOT_EXECUTED')` | five distinct computed forms: `_PROPOSE_NOT_EXECUTED + "…"` (BinOp), `**_PROPOSE_COMMON_PROPS` (dict unpacking), `_ROUND_REF_PROP` (bare Name), `[*_PROPOSE_COMMON_REQUIRED, "name"]` (Starred), `_PROPOSE_COMMON_PROPS["summary"]` (Subscript) |
| `intake_core.tools.schemas.UPDATE_ANSWER_TOOL` / `MARK_STATUS_TOOL` / `ALL_TOOLS` | **FAILS** — `Name(id='_QID_ENUM')`, `Name(id='UPDATE_ANSWER_TOOL')` | the qid enum is computed from `INTAKE_QUESTIONS`, exactly the phase-2 pattern |

So the debrief proof **must** `exec` the module (Task 3, Step 6 gives the script), and the intake-core proof uses a stronger technique that sidesteps parsing entirely: the derived spec's `parameters` is asserted to be **the same object** as the source `input_schema` (`is`, not `==`), which cannot be satisfied by a retype (Task 2).

---

## Model alias map

| Site | Model source today | Value today | Becomes | Alias in `litellm-config.yaml` |
|---|---|---|---|---|
| intake text loop | `ANTHROPIC_MODEL` **hardcoded** at `intake_text_messages.py:46` | `claude-sonnet-4-6` | `intake-text` via **new** `INTAKE_TEXT_MODEL` | **new entry** (Task 4) |
| intake coverage tracker (text) | the same value, forwarded by `text_runner:237` | `claude-sonnet-4-6` | the same `intake-text` alias | as above |
| debrief chat loop | `DEBRIEF_CHAT_MODEL` | `claude-sonnet-4-6` | `debrief-chat` | `:32` — exists, sonnet-5 |
| intake coverage tracker (voice) | `os.getenv("ANTHROPIC_MODEL_SONNET", "claude-sonnet-4-6")` at `voice-agent/src/main.py:2174` | `claude-sonnet-4-6` | `voice-intake` | `:98` — exists, **orphan today**, sonnet-5 |

**Why `intake-text` is a new alias and not `voice-intake`.** Both drive the same intake persona, so reuse is defensible. They get separate aliases because the two paths reach the model by different routes — text through `llm_core.stream_turn`, voice through pipecat (phase 7) — and because the whole deliverable of this migration is that either can be pointed at a local model without dragging the other with it. Tier is preserved: both resolve to sonnet, matching the `claude-sonnet-4-6` they replace, and inheriting phase 1's documented sonnet-4-6 → sonnet-5 bump exactly as phase 2 did.

**`voice-intake` stops being an orphan** the moment Task 4 lands, which is a small side benefit of migrating the coverage tracker.

**Ordering constraint (hard), and it is the reason for the task shapes below.** A model setting may only be flipped to an alias in the *same task* that migrates its reader — phase 2's lesson (`SCREENING_GENERATOR_MODEL`) applies verbatim. Sending the string `"debrief-chat"` to `api.anthropic.com`, or the Anthropic-shaped tool specs to `llm_core`, fails at *runtime* and is invisible to `make test`, because every runner test mocks the seam. Three couplings follow, and each collapses what looks like two tasks into one:

- **debrief tool specs ↔ debrief runner.** Converting the specs while the runner still calls `client.messages.stream` sends `{"type":"function",...}` to Anthropic, which rejects it — every debrief chat turn returns the static error, suite green. Converting the runner first sends `input_schema` to `llm_core`, which raises `ToolEmulationError` (`emulation.py:84-93`) into the runner's fail-soft — same outcome, same green suite. **Task 3 does both.**
- **`coverage_tracker` ↔ `text_runner`.** `text_runner:234-240` fires `run_coverage_tracker(anthropic_client=…)`. If `text_runner` migrates first it hands an `LLMClient` to something that calls `.messages.create` — `AttributeError`, swallowed by the tracker's own `except Exception` at `coverage_tracker.py:86` and logged as `tracker_llm_failed`. If the tracker migrates first, the reverse. Both are invisible: every `text_runner` test patches `coverage_tracker_run` with an `AsyncMock`, which accepts any kwargs and any client. **Task 4 does both, and renames the parameter so the mistake would be a loud `TypeError` rather than a silent one.**
- **`intake-core` tool specs ↔ `text_runner`.** These *can* be split, and Task 2 splits them, precisely because the change there is **additive**: a new derived export nothing consumes yet. That is the argument for the additive form over flipping the canonical shape in place — see Task 2.

---

## Test-file inventory

**Rewritten by this phase (7 backend + 2 intake-core):**

| File | Tests at HEAD | What it encodes | Task |
|---|---|---|---|
| `backend/tests/services/intake/test_anthropic_stream.py` | 2 | `MagicMock` Anthropic SSE events (`content_block_start`, `input_json_delta`) | deleted with its module in 5; **replaced by** `test_llm_stream.py` (new, 11 tests) in 1 |
| `backend/tests/services/debrief_chat/test_tool_specs.py` | 18 | `spec["input_schema"]` throughout | 3 |
| `backend/tests/services/debrief_chat/test_runner.py` | 11 | `stop_reason: "tool_use"`, `{t["name"] for t in tools}` | 3 |
| `backend/tests/api/v2/test_debrief_chat_route.py` | 27 | docstring only + one new alias assertion | 3 |
| `backend/tests/services/intake/test_text_runner.py` | 13 | `stop_reason: "tool_use"`, `anthropic_client=`, asserts `tool_use`/`tool_result` blocks at `:537-546` | 4 |
| `backend/tests/api/v2/test_intake_text_messages.py` | 4 | patches `get_anthropic_async_client` (**inertly** — see Task 4) | 4 |
| `backend/tests/api/test_dependencies_extra.py` | 17 | `test_get_anthropic_async_client_singleton` | 6 |
| `backend/tests/test_anthropic_surface.py` | 6 | pins the surviving Anthropic surface — exists to fail until phase 3 | 6 (deleted, replaced) |
| `intake-core/tests/test_tool_schemas.py` | 4 | Anthropic shape assertions (kept; 3 added) | 2 |
| `intake-core/tests/test_coverage_tracker.py` | 10 | `mock_anthropic.messages.create` | 4 |

**Deliberately untouched:** `backend/tests/services/test_end_state.py` and anything covering `candidate_detection_service.py` — raw httpx, no SDK, out of scope entirely. `voice-agent/tests/pipeline/test_tool_dispatch.py` and `voice-agent/tests/screening/conftest.py` mention Anthropic but cover `handle_update_answer` dispatch, not the tracker; Task 4 does not touch them.

### Suite arithmetic — every task, end to end

| after task | change | expected |
|---|---|---|
| baseline | — | **2167 passed, 5 skipped** |
| 1 | + `test_llm_stream.py` (11) | 2178 |
| 2 | + 2 backend tests for the derived intake tool export | 2180 |
| 3 | + 2 in `test_tool_specs.py`, + 6 in `test_runner.py`, + 1 in `test_debrief_chat_route.py` | 2189 |
| 4 | + 7 in `test_text_runner.py`, + 1 in `test_intake_text_messages.py`, + 1 coverage-tracker signature guard | 2198 |
| 5 | − 2 (`test_anthropic_stream.py`, deleted with its module) | 2196 |
| 6 | − 6 (`test_anthropic_surface.py`) − 1 (`test_get_anthropic_async_client_singleton`) + 7 (`test_no_provider_sdk.py`) | **2196** |

Final: **2196 passed, 5 skipped** — baseline +29. Skips unchanged at 5.

---

## File Structure

| Path | Change | Task |
|---|---|---|
| `backend/app/services/intake/llm_stream.py` | **new** — the streaming seam | 1 |
| `backend/tests/services/intake/test_llm_stream.py` | **new** — 11 tests | 1 |
| `litellm-config.yaml` | tool-capability comments on `debrief-chat`; new `intake-text` entry | 1, 3, 4 |
| `intake-core/intake_core/tools/schemas.py` | derived OpenAI export | 2 |
| `intake-core/intake_core/tools/__init__.py` | re-export `INTAKE_TOOLS_OPENAI` | 2 |
| `backend/app/services/debrief_chat/tool_specs.py` | 11 specs → OpenAI shape | 3 |
| `backend/app/services/debrief_chat/runner.py` | **rewritten** | 3 |
| `backend/app/api/v2/routers/debrief_chat.py` | client swap | 3 |
| `backend/app/config.py` | `DEBRIEF_CHAT_MODEL` → alias; new `INTAKE_TEXT_MODEL` | 3, 4 |
| `intake-core/intake_core/coverage_tracker.py` | `llm.complete` | 4 |
| `backend/app/services/intake/text_runner.py` | **rewritten** | 4 |
| `backend/app/api/v2/routers/intake_text_messages.py` | dependency + model + kwargs | 4 |
| `voice-agent/Dockerfile`, `voice-agent/src/main.py`, `voice-agent/scripts/smoke_test_v2.py` | tracker client swap | 4 |
| `backend/app/services/intake/anthropic_stream.py` | **deleted** | 5 |
| `backend/app/dependencies.py`, `backend/requirements.txt` | **the deletion** | 6 |
| `backend/tests/test_no_provider_sdk.py` | **new** — replaces `test_anthropic_surface.py` | 6 |

---

### Task 1: The streaming seam — `llm_stream.py`

Nothing else in this plan can be written until this exists. It is created **alongside** `anthropic_stream.py`, which both runners still import; Task 5 deletes the old module once its last consumer is gone. That ordering keeps every intermediate commit both green and *working*, and keeps `anthropic_stream.py` under test until the moment it is removed (a `git mv` of its test file would leave 50 statements uncovered against the `--cov-fail-under=85` gate).

The seam is not a translation layer — `llm_core.stream_turn` already emits the exact tagged contract, copied from `anthropic_stream.py:25-33` on purpose. It exists for three things a bare passthrough would leave to each caller, all three of which are silent-correctness bugs if forgotten: refusing an emulated alias, backfilling a missing tool-call id, and being the single mock seam both runners' tests already patch.

**Files:**
- Create: `backend/app/services/intake/llm_stream.py`
- Create: `backend/tests/services/intake/test_llm_stream.py`
- Modify: `litellm-config.yaml` (comments only in this task)

**Interfaces:**
- Consumes: `LLMClient.stream_turn(*, model, messages, tools=None, system=None, max_tokens=2048) -> AsyncIterator[tuple[str, Any]]`; `llm_core.settings.get_settings() -> LLMSettings` with `.force_json_tools: frozenset[str]`.
- Produces: `stream_llm_turn(llm, model, system, messages, tools, max_tokens=2048) -> AsyncIterator[tuple[str, Any]]` yielding `('text', str) | ('tool_call', {"id": str, "name": str, "input": dict}) | ('done', {"text": str, "stop_reason": str | None})`, with `id` guaranteed non-empty. Raises `EmulatedToolsNotStreamable`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/intake/test_llm_stream.py`:

```python
"""Tests for the streaming seam both agent loops run through.

The seam does no format translation — llm_core.stream_turn was written to the
tagged contract this codebase already had. What is tested here is the two
normalizations it adds, because both are silent-correctness bugs when absent:

* an emulated alias yields NO tool_call event at all (llm_core client.py:320-334),
  so a tool loop would run to completion having executed nothing;
* stream_turn passes the provider's tool-call id through raw, and it can be None
  (client.py:384/386/458) — which becomes an invalid tool_call_id on the NEXT
  request, i.e. a 400 after the user has already seen text stream in.

Everything here goes through llm-core's FakeLLM, whose stream_turn shares a
signature with the real client (llm-core/tests/test_fake.py asserts it), so a
test cannot pass here and fail against the gateway.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from llm_core.errors import LLMError, ToolEmulationError
from llm_core.settings import get_settings
from llm_core.types import LLMReply, ToolCall

from app.services.intake.llm_stream import (
    EmulatedToolsNotStreamable,
    stream_llm_turn,
)

_TOOL = {
    "type": "function",
    "function": {
        "name": "update_answer",
        "description": "Record an answer.",
        "parameters": {"type": "object", "properties": {"qid": {"type": "string"}}},
    },
}

# The aliases whose workloads are tool loops. Both MUST resolve to a
# tool-capable model; see test_the_streaming_aliases_declare_native_tool_support.
_STREAMING_ALIASES = ("intake-text", "debrief-chat")


@pytest.fixture
def forced_json(monkeypatch):
    """Drive LLM_FORCE_JSON_TOOLS despite get_settings() being lru_cached.

    The phase-2 report recorded the absence of a reset hook as a blocker for
    exactly this kind of test. lru_cache exposes cache_clear(), which is enough:
    clear before so the new env is read, and clear after so no later test in the
    session inherits it.
    """

    def _set(value: str):
        monkeypatch.setenv("LLM_FORCE_JSON_TOOLS", value)
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


async def _collect(gen):
    return [ev async for ev in gen]


async def test_events_and_alias_pass_through_unchanged(fake_llm):
    fake_llm.queue_text_deltas("Hello ", "there")
    events = await _collect(
        stream_llm_turn(
            fake_llm,
            model="intake-text",
            system="SYS",
            messages=[{"role": "user", "content": "hi"}],
            tools=[_TOOL],
        )
    )

    assert [k for k, _ in events] == ["text", "text", "done"]
    assert [p for k, p in events if k == "text"] == ["Hello ", "there"]
    call = fake_llm.calls[0]
    assert call["model"] == "intake-text"
    assert call["system"] == "SYS"
    assert call["streaming"] is True


async def test_done_carries_the_providers_finish_reason_verbatim(fake_llm):
    """The value is OpenAI vocabulary, NOT Anthropic's. This is spec reason 1 for
    the rewrite: any consumer comparing against "tool_use" is already broken."""
    fake_llm.queue_tool_call("update_answer", {"qid": "q1"})
    events = await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[_TOOL]
        )
    )

    done = [p for k, p in events if k == "done"][0]
    assert done["stop_reason"] == "tool_calls"
    assert done["stop_reason"] != "tool_use"


async def test_tool_call_payload_uses_input_not_arguments(fake_llm):
    fake_llm.queue_tool_call("update_answer", {"qid": "q4_must_haves"})
    events = await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[_TOOL]
        )
    )

    call = [p for k, p in events if k == "tool_call"][0]
    assert set(call) == {"id", "name", "input"}
    assert call["input"] == {"qid": "q4_must_haves"}


async def test_an_anthropic_shaped_tool_spec_is_rejected(fake_llm):
    """The migration mistake this phase is most likely to leave behind. FakeLLM
    runs the same validate_tool_shape the gateway path runs, so it fails here
    rather than as an opaque provider 400."""
    fake_llm.queue_text("never reached")
    with pytest.raises(ToolEmulationError) as exc:
        await _collect(
            stream_llm_turn(
                fake_llm,
                model="intake-text",
                system="S",
                messages=[],
                tools=[{"name": "update_answer", "input_schema": {"type": "object"}}],
            )
        )
    assert "input_schema" in str(exc.value)


async def test_an_empty_tool_list_is_sent_as_none(fake_llm):
    """The opening greeting passes tools=[]. `if tools:` in stream_turn treats []
    and None identically, and normalizing here keeps the recorded call unambiguous."""
    fake_llm.queue_text("Hey there")
    await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[]
        )
    )
    assert fake_llm.calls[0]["tools"] is None


async def test_an_emulated_alias_is_refused_when_tools_are_supplied(
    fake_llm, forced_json
):
    """stream_turn emits no tool_call event on the emulated path, so a tool loop
    would complete having executed nothing and would stream the emulated JSON to
    the user as prose. Refuse the configuration instead of degrading."""
    forced_json("intake-text,gemma-local")
    with pytest.raises(EmulatedToolsNotStreamable) as exc:
        await _collect(
            stream_llm_turn(
                fake_llm, model="intake-text", system="S", messages=[], tools=[_TOOL]
            )
        )
    assert "intake-text" in str(exc.value)
    assert fake_llm.calls == []


async def test_an_emulated_alias_is_allowed_when_no_tools_are_supplied(
    fake_llm, forced_json
):
    """run_text_opening streams a greeting with tools=[]. Nothing is emulated on
    a request that carries no tools, so refusing it would be wrong."""
    forced_json("intake-text")
    fake_llm.queue_text("Hey there")
    events = await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[]
        )
    )
    assert [k for k, _ in events][-1] == "done"


async def test_a_tool_call_with_no_id_is_backfilled(fake_llm):
    """stream_turn yields slot["id"] raw and it is None when the gateway never
    sent one. Both runners put that value in tool_call_id on the NEXT request,
    where OpenAI requires a string — a 400 one turn later."""
    fake_llm.queue_reply(
        LLMReply(
            text="",
            model="fake",
            tool_calls=[ToolCall(id="", name="update_answer", arguments={"qid": "q1"})],
            finish_reason="tool_calls",
        )
    )
    events = await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[_TOOL]
        )
    )
    call = [p for k, p in events if k == "tool_call"][0]
    assert call["id"]
    assert "update_answer" in call["id"]


async def test_backfilled_ids_are_distinct_within_a_turn(fake_llm):
    fake_llm.queue_reply(
        LLMReply(
            text="",
            model="fake",
            tool_calls=[
                ToolCall(id="", name="update_answer", arguments={"qid": "q1"}),
                ToolCall(id="", name="update_answer", arguments={"qid": "q2"}),
            ],
            finish_reason="tool_calls",
        )
    )
    events = await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[_TOOL]
        )
    )
    ids = [p["id"] for k, p in events if k == "tool_call"]
    assert len(ids) == len(set(ids)) == 2


async def test_a_real_id_is_never_rewritten(fake_llm):
    fake_llm.queue_tool_call("update_answer", {"qid": "q1"})
    events = await _collect(
        stream_llm_turn(
            fake_llm, model="intake-text", system="S", messages=[], tools=[_TOOL]
        )
    )
    assert [p for k, p in events if k == "tool_call"][0]["id"] == "fake-update_answer"


def test_the_streaming_aliases_declare_native_tool_support():
    """The OTHER way an alias becomes emulated: model_info in the proxy config.

    llm-core exposes no public capability accessor (CapabilityCache is reachable
    only through the private LLMClient._caps), so this cannot be checked at
    runtime without a private attribute read. Checking the config statically is
    the cheapest place it can fail, and it fails the moment someone points a
    streaming workload at Gemma — which would silently stop the intake agent
    persisting any answer at all.
    """
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[4] / "litellm-config.yaml").read_text()
    )
    by_name = {entry["model_name"]: entry for entry in config["model_list"]}
    for alias in _STREAMING_ALIASES:
        assert alias in by_name, f"{alias} is not defined in litellm-config.yaml"
        info = by_name[alias].get("model_info") or {}
        assert info.get("supports_function_calling") is True, alias
```

Note on the config test's path: `backend/tests/services/intake/test_llm_stream.py` → `parents[4]` is the repo root. `make test` mounts `$(PWD)/backend` at `/app`, so **the repo root is not inside the container.** Resolve this in Step 3 by making the test skip-free and container-safe — see below.

- [ ] **Step 2: Run test to verify it fails**

Run: `make test`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.intake.llm_stream'` at collection.

- [ ] **Step 3: Make the config assertion runnable inside the test image**

`make test` runs `docker run -v "$(PWD)/backend:/app" -w /app`, so only `backend/` is mounted; `litellm-config.yaml` lives at the repo root and is **not** reachable from inside the container. Do **not** solve this with a `skipif` — the plan forbids new skips, and a skipped guard is not a guard.

Add the file to the test image instead. In `backend/Dockerfile.test`, after the `llm-core` install block:

```dockerfile
# The gateway alias map. Two backend tests assert properties of it that cannot be
# checked at runtime: that the streaming aliases declare native tool support (a
# `false` there silently stops the intake agent persisting any answer), and that
# every alias a setting names actually exists. The repo root is not mounted by
# `make test`, so the file has to be baked in.
COPY litellm-config.yaml /litellm-config.yaml
```

and read it from a fixed location in the test, replacing the `parents[4]` line:

```python
_CONFIG_PATHS = (
    Path("/litellm-config.yaml"),                                  # baked into the test image
    Path(__file__).resolve().parents[4] / "litellm-config.yaml",   # repo checkout
)


def _load_gateway_config() -> dict:
    for path in _CONFIG_PATHS:
        if path.exists():
            return yaml.safe_load(path.read_text())
    raise AssertionError(f"litellm-config.yaml not found at any of {_CONFIG_PATHS}")
```

`PyYAML` is already an installed transitive dependency in the backend image (it arrives with `uvicorn[standard]`); confirm with `docker run --rm openrecruiting-backend-test python -c "import yaml; print(yaml.__version__)"` before relying on it, and add `PyYAML>=6.0` to `backend/requirements.txt` if that fails.

- [ ] **Step 4: Write `llm_stream.py`**

Create `backend/app/services/intake/llm_stream.py`:

```python
"""The streaming seam both agent loops run through.

Replaces anthropic_stream.py. The tagged event contract is UNCHANGED —
('text', str) | ('tool_call', {id, name, input}) | ('done', {text, stop_reason})
— because llm_core.stream_turn was deliberately written to it
(llm-core/llm_core/client.py:275-282, "Contract copied from the Anthropic-era
wrapper so consumers do not change"). This module therefore performs no format
translation at all. What it adds is the two normalizations a bare passthrough
would leave to every caller, both of which are silent-correctness bugs when
forgotten, plus the single seam the runner tests patch.

1. REFUSING AN EMULATED ALIAS. On an alias without native function calling,
   stream_turn pushes the tool schema into a system message and never parses the
   reply back — no tool_call event is emitted at all (client.py:320-334, and its
   docstring says so in as many words). Both callers of this module are tool
   loops: the intake runner would silently never persist a recruiter's answer,
   and the debrief runner would answer over no retrieved data with no action
   proposable. The emulated JSON would additionally be streamed to the user as
   chat prose. There is no error and no failing request anywhere in that, so the
   configuration is refused rather than degraded.

   This covers the LLM_FORCE_JSON_TOOLS override only. The other route to an
   emulated alias is `model_info: {supports_function_calling: false}` in
   litellm-config.yaml, which llm-core exposes no public accessor for; that one
   is pinned statically by test_llm_stream.py.

2. BACKFILLING A MISSING TOOL-CALL ID. stream_turn yields slot["id"] verbatim,
   and it is None whenever the gateway did not echo an id (client.py:384, 386,
   458). Both callers write that value into `tool_call_id` on the FOLLOWING
   request, where OpenAI requires a string. A None there is a provider 400 one
   turn later — after the user has already watched text stream in.

stop_reason in the done event is the provider's finish_reason passed through
untouched, so it speaks OpenAI's vocabulary ("stop", "tool_calls", "length").
Neither loop branches on it; both are driven by whether tool calls arrived. That
is deliberate — see text_runner.run_text_turn.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import structlog
from llm_core.settings import get_settings

logger = structlog.get_logger(__name__)


class EmulatedToolsNotStreamable(RuntimeError):
    """A tool-using stream was pointed at an alias whose tools would be emulated.

    Not an LLMError: nothing reached a provider, and this is a configuration bug
    in this deployment rather than a provider failure. Raising a distinct type
    keeps it out of the `except LLMError` handlers that treat provider trouble as
    transient and retryable — this one will never succeed on a retry.
    """


async def stream_llm_turn(
    llm,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int = 2048,
) -> AsyncIterator[tuple[str, Any]]:
    """Stream a single assistant turn as tagged events.

    ('text', str)        — incremental prose chunk. SEVERAL per turn; consumers
                           must accumulate and may not assume one event.
    ('tool_call', {...}) — a completed call: {id, name, input}. `input`, not
                           `arguments` — the streaming event key differs from the
                           ToolCall field name on the non-streaming path. Emitted
                           only once the argument JSON is fully assembled.
    ('done', {...})      — {text, stop_reason}, exactly once, last.

    `model` is a gateway alias, never a provider model id.
    """
    if tools and model in get_settings().force_json_tools:
        raise EmulatedToolsNotStreamable(
            f"alias {model!r} is listed in LLM_FORCE_JSON_TOOLS, so its tools "
            "would be emulated. llm_core.stream_turn emits no tool_call event on "
            "that path, so this tool loop would run to completion having executed "
            "nothing while streaming the emulated JSON to the user as prose. "
            "Point this workload at a tool-capable alias."
        )

    backfilled = 0
    async for kind, payload in llm.stream_turn(
        model=model,
        system=system,
        messages=messages,
        tools=tools or None,
        max_tokens=max_tokens,
    ):
        if kind == "tool_call" and not payload.get("id"):
            backfilled += 1
            name = payload.get("name")
            # Deterministic and unique within the turn. The caller holds one dict
            # per call and reads its id twice — once for the assistant message's
            # tool_calls entry, once for the matching tool result — so stability
            # matters more than the value.
            payload = {**payload, "id": f"call_{backfilled}_{name}"}
            logger.warning(
                "llm_stream_tool_call_id_backfilled", alias=model, name=name
            )
        yield (kind, payload)
```

- [ ] **Step 5: Annotate the streaming aliases in `litellm-config.yaml`**

Above the `debrief-chat` entry (`:32`), add:

```yaml
  # STREAMING TOOL LOOP — supports_function_calling MUST stay true.
  # llm_core.stream_turn emits no tool_call event on the emulated path, so a
  # false here does not degrade this workload, it silently disables it: the
  # debrief agent would answer a recruiter over no retrieved data and could
  # never propose an action. Pinned by
  # backend/tests/services/intake/test_llm_stream.py.
```

- [ ] **Step 6: Run test to verify it passes**

Run: `make test`
Expected: PASS — **2178 passed, 5 skipped** (2167 + 11).

- [ ] **Step 7: Self-review and commit**

```bash
git diff --cached
git add backend/app/services/intake/llm_stream.py backend/tests/services/intake/test_llm_stream.py backend/Dockerfile.test litellm-config.yaml
git commit -m "feat(intake): add the llm-core streaming seam, refusing emulated tool aliases"
```

---

### Task 2: `intake-core` gains an OpenAI-shaped tool export, additively

`text_runner.py:262` passes `INTAKE_TOOLS_ANTHROPIC` — which is `intake_core.tools.schemas.ALL_TOOLS`, two specs carrying `input_schema`. `llm_core` rejects that shape rather than translating it (CHECKPOINT fact #5), so Task 4 cannot land without an OpenAI-shaped version of these two specs.

**Why additive rather than flipping the canonical shape.** `voice-agent/src/main.py:43` imports the same `ALL_TOOLS` and hands it to pipecat's `AnthropicLLMService` at `:2192`. That is phase 7's surface. Flipping `ALL_TOOLS` in place would break the running voice agent at request time, with **no test anywhere that would notice** — `grep -rn "ALL_TOOLS" voice-agent/tests` returns nothing. An additive derived export breaks nothing, is consumed only by Task 4, and lets phase 4 make the OpenAI form canonical and delete the Anthropic one at the same moment phase 7 stops needing it.

**Why this is not the "Anthropic-shaped compatibility facade" the spec forbids.** The spec's decision #2 forbids call sites talking to the gateway in Anthropic shape. This is the opposite direction: one schema body, rendered into the shape each of the two remaining consumers needs, with the OpenAI rendering derived **by reference** from the Anthropic one. It ships with an expiry date attached to phase 4.

**Files:**
- Modify: `intake-core/intake_core/tools/schemas.py`
- Modify: `intake-core/intake_core/tools/__init__.py`
- Test: `intake-core/tests/test_tool_schemas.py`
- Test: `backend/tests/services/intake/test_intake_tool_export.py` (create)

**Interfaces:**
- Consumes: the existing `UPDATE_ANSWER_TOOL`, `MARK_STATUS_TOOL`, `ALL_TOOLS` dicts, unmodified.
- Produces: `intake_core.tools.schemas.ALL_TOOLS_OPENAI`, re-exported as `intake_core.tools.INTAKE_TOOLS_OPENAI` — a list of `{"type": "function", "function": {"name", "description", "parameters"}}` that `llm_core.emulation.validate_tool_shape` accepts.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/intake/test_intake_tool_export.py`:

```python
"""The intake tool specs, in the shape the gateway accepts.

text_runner hands these to llm_core.stream_turn, which REJECTS Anthropic-shaped
specs rather than translating them (llm_core/emulation.py:84-93). This is the
backend-side guard for that; intake-core's own suite (not run by `make test`)
covers the derivation itself.
"""
from llm_core.emulation import validate_tool_shape

from intake_core.tools import INTAKE_TOOLS_ANTHROPIC, INTAKE_TOOLS_OPENAI


def test_the_openai_export_is_accepted_by_llm_core():
    entries = validate_tool_shape(INTAKE_TOOLS_OPENAI)
    assert [name for name, _description, _schema in entries] == [
        "update_answer",
        "mark_status",
    ]


def test_the_two_exports_describe_the_same_two_tools():
    """Proof the specs were MOVED, not retyped: `parameters` is the SAME OBJECT
    as the source `input_schema`, which no retype can satisfy. A diff cannot show
    this, because reindentation touches every line."""
    assert len(INTAKE_TOOLS_OPENAI) == len(INTAKE_TOOLS_ANTHROPIC) == 2
    for old, new in zip(INTAKE_TOOLS_ANTHROPIC, INTAKE_TOOLS_OPENAI):
        assert new["type"] == "function"
        assert new["function"]["name"] == old["name"]
        assert new["function"]["description"] is old["description"]
        assert new["function"]["parameters"] is old["input_schema"]
```

And in `intake-core/tests/test_tool_schemas.py`, append (keeping all four existing tests untouched):

```python
from intake_core.tools.schemas import ALL_TOOLS_OPENAI


def test_openai_export_mirrors_every_anthropic_spec():
    assert len(ALL_TOOLS_OPENAI) == len(ALL_TOOLS)
    for old, new in zip(ALL_TOOLS, ALL_TOOLS_OPENAI):
        assert set(new) == {"type", "function"}
        assert new["type"] == "function"
        assert set(new["function"]) == {"name", "description", "parameters"}
        assert new["function"]["name"] == old["name"]
        assert new["function"]["description"] is old["description"]
        assert new["function"]["parameters"] is old["input_schema"]


def test_openai_export_carries_the_computed_qid_enum():
    """The enum is computed from INTAKE_QUESTIONS, which is why these specs are
    not literal_eval-able and why the derivation shares the object rather than
    copying it."""
    for tool in ALL_TOOLS_OPENAI:
        enum = tool["function"]["parameters"]["properties"]["qid"]["enum"]
        assert len(enum) == 9
        assert "q4_must_haves" in enum


def test_the_anthropic_export_is_untouched_for_the_voice_agent():
    """voice-agent/src/main.py:43 still imports ALL_TOOLS and hands it to
    pipecat's AnthropicLLMService. Phase 7 moves it; until then this shape is
    load-bearing and no voice-agent test would catch its removal."""
    for tool in ALL_TOOLS:
        assert set(tool) == {"name", "description", "input_schema"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test`
Expected: FAIL — `ImportError: cannot import name 'INTAKE_TOOLS_OPENAI' from 'intake_core.tools'`.

- [ ] **Step 3: Derive the export**

Append to `intake-core/intake_core/tools/schemas.py` (nothing above this line changes):

```python
def _as_openai_tool(tool: dict) -> dict:
    """Render an Anthropic-shaped spec in the OpenAI function shape.

    `parameters` is the SAME OBJECT as `input_schema`, not a copy. That is
    deliberate: it makes "the schema was moved, not retyped" true by
    construction and assertable with `is`, which a diff cannot show because
    reindentation touches every line. Both lists are read-only module data and
    nothing in this repo mutates a tool schema.
    """
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


# TEMPORARY DUAL SHAPE, and it has an owner.
#
# ALL_TOOLS stays Anthropic-shaped because voice-agent/src/main.py:43 still hands
# it to pipecat's AnthropicLLMService — phase 7's surface, with no test covering
# it. ALL_TOOLS_OPENAI is what the backend text runner sends to the LiteLLM
# gateway from phase 3 onward; llm_core rejects `input_schema` outright rather
# than translating it.
#
# Phase 4 makes the OpenAI form canonical and deletes _as_openai_tool together
# with the Anthropic one, at the same moment phase 7 stops needing it.
ALL_TOOLS_OPENAI: list[dict] = [_as_openai_tool(tool) for tool in ALL_TOOLS]
```

Update the module docstring line 1 from `"""Anthropic tool-use schemas for update_answer + mark_status."""` to:

```python
"""Tool-use schemas for update_answer + mark_status, in both wire shapes.

ALL_TOOLS is Anthropic-shaped and still feeds the voice agent (phase 7).
ALL_TOOLS_OPENAI is derived from it and feeds the backend text runner through the
LiteLLM gateway. See _as_openai_tool for why the derivation shares objects.
"""
```

- [ ] **Step 4: Re-export it**

In `intake-core/intake_core/tools/__init__.py`, change `:9` and `:15` and `:78`:

```python
from intake_core.tools.schemas import ALL_TOOLS, ALL_TOOLS_OPENAI
...
INTAKE_TOOLS_ANTHROPIC: list[dict] = ALL_TOOLS
# The same two tools in the shape the LiteLLM gateway speaks. The backend text
# runner uses this one; the voice agent still uses the Anthropic list above.
INTAKE_TOOLS_OPENAI: list[dict] = ALL_TOOLS_OPENAI
...
__all__ = [
    "INTAKE_TOOLS_ANTHROPIC",
    "INTAKE_TOOLS_OPENAI",
    "handle_tool_call",
    "ahandle_tool_call",
]
```

- [ ] **Step 5: Run both suites**

```bash
make test
cd intake-core && python -m pytest -q && cd ..
```

Expected: `make test` PASS — **2180 passed, 5 skipped** (2178 + 2). `intake-core` PASS at its own count, +3 over whatever it was. **Paste both counts in the commit body**; the intake-core suite is not in the acceptance gate and an unrun change there is an unverified change.

- [ ] **Step 6: Self-review and commit**

```bash
git diff --cached
git add intake-core/intake_core/tools backend/tests/services/intake/test_intake_tool_export.py intake-core/tests/test_tool_schemas.py
git commit -m "feat(intake-core): derive an OpenAI-shaped view of the intake tool specs"
```

---

### Task 3: Rewrite `debrief_chat/runner.py`, converting its 11 tool specs with it

These cannot be split. Converting the specs while the runner still calls `client.messages.stream` sends `{"type": "function", ...}` to Anthropic, which rejects it; converting the runner first sends `input_schema` to `llm_core`, which raises `ToolEmulationError`. Both land in the runner's fail-soft as the static error message, both leave `make test` green because every runner test patches the seam, and both break every live debrief chat turn.

The debrief runner is taken before the text runner because it is the smaller of the two rewrites and has no cross-package coupling.

**Files:**
- Modify: `backend/app/services/debrief_chat/tool_specs.py`
- Modify: `backend/app/services/debrief_chat/runner.py`
- Modify: `backend/app/api/v2/routers/debrief_chat.py`
- Modify: `backend/app/config.py`
- Modify: `litellm-config.yaml` (comment only — the `debrief-chat` alias already exists)
- Test: `backend/tests/services/debrief_chat/test_tool_specs.py`
- Test: `backend/tests/services/debrief_chat/test_runner.py`
- Test: `backend/tests/api/v2/test_debrief_chat_route.py`

**Interfaces:**
- Consumes: `stream_llm_turn` (Task 1); `app.dependencies.get_llm_client`.
- Produces: `READ_TOOL_SPECS` / `PROPOSE_TOOL_SPECS` in OpenAI shape; `DebriefChatRunner(*, llm, model, ...)` — the keyword `client` becomes `llm`; `DEBRIEF_CHAT_MODEL` default becomes the alias `debrief-chat`. `ChatEvent` stream shape unchanged.

- [ ] **Step 1: Write the failing test**

In `backend/tests/services/debrief_chat/test_tool_specs.py`, all 18 existing tests keep their assertions and change only how they reach the spec. Add two accessors at the top and re-point every `spec["input_schema"]` / `spec["name"]` / `spec["description"]`:

```python
"""Unit tests for the debrief chat tool specs — OpenAI function shape.

Eleven tools: three grounded read tools the runner executes in-loop, and eight
propose_* tools the runner intercepts without executing. The assertions below are
the ones that were here before the phase-3 shape change, re-pointed at
["function"]["parameters"]; nothing about the schemas themselves changed, which
is proven separately by parsing both revisions (see the plan's Task 3 Step 6).
"""

from llm_core.emulation import validate_tool_shape

from app.services.debrief_chat.tool_specs import PROPOSE_TOOL_SPECS, READ_TOOL_SPECS


def _fn(spec: dict) -> dict:
    return spec["function"]


def _schema(spec: dict) -> dict:
    return spec["function"]["parameters"]


def _by_name():
    return {_fn(spec)["name"]: spec for spec in READ_TOOL_SPECS}


def _propose_by_name():
    return {_fn(spec)["name"]: spec for spec in PROPOSE_TOOL_SPECS}
```

Then mechanically: `spec["name"]` → `_fn(spec)["name"]`, `spec["description"]` → `_fn(spec)["description"]`, `spec["input_schema"]` → `_schema(spec)`. Example, `test_get_candidate_detail_requires_candidate_id`:

```python
def test_get_candidate_detail_requires_candidate_id():
    spec = _by_name()["get_candidate_detail"]
    assert _schema(spec)["required"] == ["candidate_id"]
    assert "candidate_id" in _schema(spec)["properties"]
```

Add two new tests at the end:

```python
def test_every_spec_is_in_the_shape_llm_core_accepts():
    """llm_core rejects `input_schema` rather than translating it, and it does so
    on the native path as well as the emulated one — so a forgotten conversion is
    an exception at call time, not a provider 400. This catches it at import."""
    entries = validate_tool_shape(READ_TOOL_SPECS + PROPOSE_TOOL_SPECS)
    assert len(entries) == 11
    for spec in READ_TOOL_SPECS + PROPOSE_TOOL_SPECS:
        assert set(spec) == {"type", "function"}
        assert spec["type"] == "function"
        assert set(spec["function"]) == {"name", "description", "parameters"}


def test_eleven_tools_not_twelve():
    """Phase 1's hazard note and the phase-3 brief both say 12. Counted from the
    source it is 3 + 8. Pinned so the number stops drifting in prose."""
    assert len(READ_TOOL_SPECS) == 3
    assert len(PROPOSE_TOOL_SPECS) == 8
```

In `backend/tests/services/debrief_chat/test_runner.py`: rename the `_runner` helper's `client=MagicMock()` to `llm=MagicMock()`, change every scripted `stop_reason` from `"tool_use"` to `"tool_calls"`, and change `:244` from `{t["name"] for t in seen["tools"]}` to `{t["function"]["name"] for t in seen["tools"]}`. The eleven existing tests keep every other assertion.

Add six new tests. The first three drive the **real** `stream_llm_turn` over `fake_llm` rather than patching the seam — that is the only way to assert what actually reaches the gateway, and the request history is the whole point of this rewrite:

```python
from llm_core.types import LLMReply, ToolCall

from app.services.debrief_chat.tool_specs import READ_TOOL_SPECS


def _runner_over(fake_llm, *, repo, read_tools, max_iters=4):
    """A runner wired to the REAL seam over llm-core's FakeLLM.

    The other tests patch stream_llm_turn and script events; these three must not,
    because what is being asserted is the messages array the second request
    carries — which only exists if the real seam runs."""
    return DebriefChatRunner(
        llm=fake_llm,
        model="debrief-chat",
        max_iters=max_iters,
        max_tokens=1024,
        packet_body=_packet(),
        repo=repo,
        read_tools=read_tools,
        system_prompt="SYSTEM",
        packet_id=PACKET_ID,
    )


@pytest.mark.asyncio
async def test_request_history_is_openai_shaped(fake_llm):
    """The crux of the rewrite. The second request must carry the assistant turn
    with a sibling `tool_calls` array whose arguments are a JSON STRING, followed
    by one {"role": "tool", "tool_call_id": ...} message per call — NOT an
    Anthropic content-block list with tool_result entries inside a user message,
    which OpenAI's Chat Completions schema cannot accept at all."""
    import json

    repo = _repo()
    read_tools = _read_tools({"candidate_id": CAND_A, "rounds": []})
    fake_llm.queue_reply(
        LLMReply(
            text="Let me check.",
            model="fake",
            tool_calls=[
                ToolCall(
                    id="t1",
                    name="get_candidate_detail",
                    arguments={"candidate_id": CAND_A},
                )
            ],
            finish_reason="tool_calls",
        )
    )
    fake_llm.queue_text("Ada's round-2 rating is strong.")

    await _collect(_runner_over(fake_llm, repo=repo, read_tools=read_tools).run("why?"))

    assert len(fake_llm.calls) == 2
    second = fake_llm.calls[1]["messages"]
    assistant, tool_msg = second[-2], second[-1]

    assert assistant["role"] == "assistant"
    assert isinstance(assistant.get("content"), str)
    assert "tool_use" not in json.dumps(assistant)
    call = assistant["tool_calls"][0]
    assert call == {
        "id": "t1",
        "type": "function",
        "function": {
            "name": "get_candidate_detail",
            "arguments": json.dumps({"candidate_id": CAND_A}),
        },
    }
    assert isinstance(call["function"]["arguments"], str)

    assert tool_msg == {
        "role": "tool",
        "tool_call_id": "t1",
        "content": str({"candidate_id": CAND_A, "rounds": []}),
    }


@pytest.mark.asyncio
async def test_the_loop_continues_on_tool_calls_not_on_a_stop_reason_string(fake_llm):
    """Phase 1 hazard #2, pinned. The old code was
    `if stop_reason != "tool_use" ... break`, and stream_turn passes the
    provider's finish_reason through untouched — so the string is "tool_calls"
    here, and would be None from a gateway that never sends one. The loop is
    driven by whether calls arrived, so no string comparison can break it again."""
    repo = _repo()
    fake_llm.queue_reply(
        LLMReply(
            text="",
            model="fake",
            tool_calls=[
                ToolCall(id="t1", name="get_candidate_detail",
                         arguments={"candidate_id": CAND_A})
            ],
            finish_reason=None,  # NOT "tool_calls", NOT "tool_use"
        )
    )
    fake_llm.queue_text("done")

    read_tools = _read_tools()
    await _collect(_runner_over(fake_llm, repo=repo, read_tools=read_tools).run("go"))

    read_tools.dispatch.assert_awaited_once()
    assert len(fake_llm.calls) == 2


@pytest.mark.asyncio
async def test_the_eleven_tools_reach_the_gateway_in_openai_shape(fake_llm):
    repo = _repo()
    fake_llm.queue_text("ok")
    await _collect(_runner_over(fake_llm, repo=repo, read_tools=_read_tools()).run("hi"))

    sent = fake_llm.calls[0]
    assert sent["model"] == "debrief-chat"
    assert len(sent["tools"]) == 11
    assert all(t["type"] == "function" for t in sent["tools"])
    assert "get_candidate_detail" in {t["function"]["name"] for t in sent["tools"]}


@pytest.mark.asyncio
async def test_a_propose_call_with_incomplete_arguments_is_not_an_action():
    """CHECKPOINT fact #3 at this site. A truncated argument buffer arrives as
    input={} (llm_core client.py:436-449). Passed through, it becomes a persisted
    confirm card proposing a hiring decision that names no candidate and no
    verdict — a write action against a real person, invented from a degraded
    reply. The /actions endpoint would reject it, but the recruiter still saw it
    and the history still keeps it."""
    repo = _repo()
    runner = _runner(repo=repo, read_tools=_read_tools())

    async def fake_stream(**kwargs):
        yield ("text", "Here you go.")
        yield ("tool_call", {"id": "p1", "name": "propose_record_decision", "input": {}})
        yield ("done", {"text": "Here you go.", "stop_reason": "tool_calls"})

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=fake_stream):
        events = await _collect(runner.run("record a hire"))

    assert [e for e in events if e.type == "proposed_action"] == []
    assistant_turn = repo.append_turn.await_args_list[1].args[1]
    assert assistant_turn["proposed_action"] is None
    assert assistant_turn["text"] == "Here you go."


@pytest.mark.asyncio
async def test_a_read_call_with_incomplete_arguments_is_not_dispatched():
    repo = _repo()
    read_tools = _read_tools()
    runner = _runner(repo=repo, read_tools=read_tools)

    call_count = 0

    async def fake_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield ("tool_call", {"id": "t1", "name": "get_candidate_detail", "input": {}})
            yield ("done", {"text": "", "stop_reason": "tool_calls"})
        else:
            yield ("text", "I need a candidate id.")
            yield ("done", {"text": "I need a candidate id.", "stop_reason": "stop"})

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=fake_stream):
        events = await _collect(runner.run("detail please"))

    read_tools.dispatch.assert_not_awaited()
    assert call_count == 2  # the model is told what was missing and gets to retry
    assert not [e for e in events if e.type == "error"]


@pytest.mark.asyncio
async def test_an_emulated_alias_fails_soft_rather_than_answering_blind(fake_llm):
    """stream_llm_turn refuses the configuration; the runner's fail-soft turns
    that into the static error rather than an answer over no data."""
    repo = _repo()
    runner = _runner_over(fake_llm, repo=repo, read_tools=_read_tools())

    async def refuse(**kwargs):
        raise EmulatedToolsNotStreamable("debrief-chat emulates tools")
        yield  # pragma: no cover — make this an async generator

    with patch("app.services.debrief_chat.runner.stream_llm_turn", new=refuse):
        events = await _collect(runner.run("why?"))

    errors = [e for e in events if e.type == "error"]
    assert len(errors) == 1
    assert "emulates" not in errors[0].data["message"]  # static message, no leak
```

Import `EmulatedToolsNotStreamable` from `app.services.intake.llm_stream` at the top of the test file.

In `backend/tests/api/v2/test_debrief_chat_route.py`: fix the module docstring (`"isolation from the Anthropic loop"` → `"isolation from the gateway loop"`) and extend `test_build_runner_constructs_real_runner` with the alias assertion:

```python
def test_build_runner_constructs_real_runner():
    row = _packet_row()
    runner = chat_router._build_runner(row, _current(), MagicMock())
    assert isinstance(runner, DebriefChatRunner)


def test_build_runner_passes_the_configured_alias():
    """The factory calls get_llm_client() directly rather than through Depends, so
    app.dependency_overrides is NOT a seam here — this is the only test that sees
    which model string the runner is actually built with."""
    runner = chat_router._build_runner(_packet_row(), _current(), MagicMock())
    assert runner._model == "debrief-chat"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test`
Expected: FAIL — `KeyError: 'function'` in the tool-spec tests and `TypeError: DebriefChatRunner.__init__() got an unexpected keyword argument 'llm'`.

- [ ] **Step 3: Convert the 11 tool specs**

The envelope change is exactly phase 2's, applied 11 times: add `"type": "function"` at the top, move `name` and `description` under `function`, rename `input_schema` to `parameters` and move it under `function`. **Nothing inside a `description` string or a schema body is edited.** Do not retype a schema; move it.

Before (`tool_specs.py:44-62`, the first of eleven):

```python
    {
        "name": "get_candidate_detail",
        "description": (
            "Fetch one candidate's rounds with per-round rating, evaluation summary, "
            "outcome, and transcript availability. Use this to explain where a "
            "candidate's score came from or to compare rounds. The candidate must be "
            "one of the candidates in this debrief packet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_id": {
                    "type": "string",
                    "description": "Id of a candidate in this packet.",
                },
            },
            "required": ["candidate_id"],
        },
    },
```

After:

```python
    {
        "type": "function",
        "function": {
            "name": "get_candidate_detail",
            "description": (
                "Fetch one candidate's rounds with per-round rating, evaluation summary, "
                "outcome, and transcript availability. Use this to explain where a "
                "candidate's score came from or to compare rounds. The candidate must be "
                "one of the candidates in this debrief packet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "description": "Id of a candidate in this packet.",
                    },
                },
                "required": ["candidate_id"],
            },
        },
    },
```

Apply identically to the other two read specs and all eight propose specs. The computed forms stay exactly as they are — `_PROPOSE_NOT_EXECUTED + "…"`, `**_PROPOSE_COMMON_PROPS`, `_ROUND_REF_PROP`, `[*_PROPOSE_COMMON_REQUIRED, "name"]`, `_PROPOSE_COMMON_PROPS["summary"]` — they simply sit one level deeper. `_PROPOSE_COMMON_PROPS`, `_PROPOSE_COMMON_REQUIRED` and `_ROUND_REF_PROP` themselves are **not** touched.

Update the module docstring line 1: `"""Anthropic tool definitions for the debrief chat agent."""` → `"""Tool definitions for the debrief chat agent, in OpenAI function shape."""`, and add after the existing paragraphs:

```python
OpenAI function shape ({"type": "function", "function": {"name", "description",
"parameters"}}) because llm_core speaks OpenAI to the LiteLLM gateway and REJECTS
Anthropic-shaped specs rather than translating them
(llm-core/llm_core/emulation.py:84-93). The schema bodies are unchanged from the
Anthropic revision; see the plan's Task 3 for the parse-both-revisions proof.
```

- [ ] **Step 4: Rewrite the runner**

`runner.py:25-34`, before:

```python
from app.services.debrief_chat.tool_specs import PROPOSE_TOOL_SPECS, READ_TOOL_SPECS
from app.services.intake.anthropic_stream import stream_llm_turn

logger = structlog.get_logger(__name__)

# The model is offered both read tools (executed in-loop) and propose tools
# (intercepted, never executed). The propose-name set IS the propose tool specs.
_TOOL_SPECS = READ_TOOL_SPECS + PROPOSE_TOOL_SPECS
_READ_TOOL_NAMES = {spec["name"] for spec in READ_TOOL_SPECS}
_PROPOSE_TOOL_NAMES = {spec["name"] for spec in PROPOSE_TOOL_SPECS}
```

after:

```python
import json

from app.services.debrief_chat.tool_specs import PROPOSE_TOOL_SPECS, READ_TOOL_SPECS
from app.services.intake.llm_stream import stream_llm_turn

logger = structlog.get_logger(__name__)

# The model is offered both read tools (executed in-loop) and propose tools
# (intercepted, never executed). The propose-name set IS the propose tool specs.
_TOOL_SPECS = READ_TOOL_SPECS + PROPOSE_TOOL_SPECS
_READ_TOOL_NAMES = {spec["function"]["name"] for spec in READ_TOOL_SPECS}
_PROPOSE_TOOL_NAMES = {spec["function"]["name"] for spec in PROPOSE_TOOL_SPECS}

# What each tool must carry to be a real call. A truncated argument buffer
# arrives as input={} (llm_core client.py:436-449) and is otherwise
# indistinguishable from a genuine call of all-defaults — the recurring failure
# shape in this codebase, found three times in phase 2. Keyed on the schema's
# declared `required` set, as those fixes were.
_REQUIRED_ARGS = {
    spec["function"]["name"]: frozenset(
        spec["function"]["parameters"].get("required") or []
    )
    for spec in _TOOL_SPECS
}


def _missing_args(tool_call: dict) -> frozenset[str]:
    """Required properties absent from a streamed call's arguments."""
    supplied = set((tool_call.get("input") or {}).keys())
    return _REQUIRED_ARGS.get(tool_call.get("name"), frozenset()) - supplied
```

Module docstring: replace the closing paragraph

```python
Streaming reuses the intake `stream_llm_turn` seam verbatim (same Anthropic SDK
idiom, same mock surface in tests).
```

with

```python
Streaming goes through the intake `stream_llm_turn` seam over llm_core, so the
model is a gateway alias and nothing here names a provider. The in-loop request
history is OpenAI-shaped: an assistant message carrying a sibling `tool_calls`
array whose arguments are a JSON STRING, followed by one
{"role": "tool", "tool_call_id": ...} message per call. It was Anthropic content
blocks before phase 3, which OpenAI's Chat Completions schema cannot accept.
```

and line 1: `"""DebriefChatRunner — the bounded Anthropic tool-use loop for debrief chat."""` → `"""DebriefChatRunner — the bounded gateway tool-use loop for debrief chat."""`

`runner.py:41-63` — `__init__`, before `client,` after `llm,`; `self._client = client` → `self._llm = llm`.

`runner.py:100-107`, before:

```python
                async for kind, payload in stream_llm_turn(
                    client=self._client,
                    model=self._model,
```

after:

```python
                async for kind, payload in stream_llm_turn(
                    llm=self._llm,
                    model=self._model,
```

`runner.py:117-133`, before:

```python
                propose_call = next(
                    (tc for tc in tool_calls if tc.get("name") in _PROPOSE_TOOL_NAMES),
                    None,
                )
                if propose_call is not None:
                    proposed_action = {
                        "kind": propose_call.get("name"),
                        "input": propose_call.get("input", {}),
                    }
                    yield ChatEvent(type="proposed_action", data=proposed_action)
                    break

                read_calls = [
                    tc for tc in tool_calls if tc.get("name") in _READ_TOOL_NAMES
                ]
                if stop_reason != "tool_use" or not read_calls:
                    break
```

after:

```python
                propose_call = next(
                    (tc for tc in tool_calls if tc.get("name") in _PROPOSE_TOOL_NAMES),
                    None,
                )
                if propose_call is not None:
                    missing = _missing_args(propose_call)
                    if missing:
                        # A degraded reply must never become a confirm card. This
                        # one would propose a write against a real candidate while
                        # naming neither the candidate nor the verdict, and it is
                        # persisted on the turn — the same shape as phase 2's
                        # fabricated authenticity verdict. The turn falls through
                        # and ends as text, which is what the model produced.
                        logger.warning(
                            "debrief_chat_propose_arguments_incomplete",
                            packet_id=self._packet_id,
                            tool=propose_call.get("name"),
                            missing=sorted(missing),
                        )
                    else:
                        proposed_action = {
                            "kind": propose_call.get("name"),
                            "input": propose_call.get("input", {}),
                        }
                        yield ChatEvent(type="proposed_action", data=proposed_action)
                        break

                read_calls = [
                    tc for tc in tool_calls if tc.get("name") in _READ_TOOL_NAMES
                ]
                # Driven by whether calls arrived, NOT by a stop_reason string.
                # This was `stop_reason != "tool_use"`, and stream_turn passes the
                # provider's finish_reason through untouched — so the value is
                # "tool_calls" today and None from a gateway that omits it.
                # Correcting the string would leave the same class of bug in
                # place; presence of calls is what the loop actually depends on.
                if not read_calls:
                    break
```

Note the `stop_reason` local at `:98`/`:115` is now unused by control flow. **Keep it** — it is still assigned from the `done` event and is worth logging; add it to the iteration-guard warning at `:136-140` as `stop_reason=stop_reason` so it stays observable.

`runner.py:143-181`, before:

```python
                assistant_content: list[dict[str, Any]] = []
                if iteration_text_parts:
                    assistant_content.append(
                        {"type": "text", "text": "".join(iteration_text_parts)}
                    )
                for tc in read_calls:
                    assistant_content.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": tc.get("input", {}),
                        }
                    )
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results: list[dict[str, Any]] = []
                for tc in read_calls:
                    try:
                        result = await self._read_tools.dispatch(
                            tc["name"], tc.get("input", {})
                        )
                        content = str(result)
                    except Exception as exc:  # noqa: BLE001 — per-tool fail-soft
                        logger.warning(
                            "debrief_chat_read_tool_failed",
                            packet_id=self._packet_id,
                            tool=tc.get("name"),
                            error=str(exc),
                        )
                        content = "couldn't fetch that data right now"
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc["id"],
                            "content": content,
                        }
                    )
                messages.append({"role": "user", "content": tool_results})
```

after:

```python
                # OpenAI-shaped assistant turn: content is a STRING, the calls
                # live in a sibling `tool_calls` array, and `arguments` is a JSON
                # string rather than the decoded dict the event carried. Both
                # empty forms are omitted: some providers behind the gateway
                # reject content: null and tool_calls: [].
                assistant: dict[str, Any] = {"role": "assistant"}
                text = "".join(iteration_text_parts)
                if text:
                    assistant["content"] = text
                assistant["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc.get("input") or {}),
                        },
                    }
                    for tc in read_calls
                ]
                messages.append(assistant)

                # One {"role": "tool"} message PER CALL, each carrying the id it
                # answers. Every entry in the assistant turn's tool_calls must be
                # answered before the next assistant turn or the gateway 400s.
                for tc in read_calls:
                    missing = _missing_args(tc)
                    if missing:
                        # Not dispatched: the arguments are degraded, and telling
                        # the model exactly what is absent lets the next iteration
                        # retry. Dispatching {} would reach the same refusal from
                        # DebriefReadTools, but unnamed and unlogged.
                        logger.warning(
                            "debrief_chat_read_arguments_incomplete",
                            packet_id=self._packet_id,
                            tool=tc.get("name"),
                            missing=sorted(missing),
                        )
                        content = (
                            "that call was missing required properties: "
                            f"{', '.join(sorted(missing))}"
                        )
                    else:
                        try:
                            result = await self._read_tools.dispatch(
                                tc["name"], tc.get("input", {})
                            )
                            content = str(result)
                        except Exception as exc:  # noqa: BLE001 — per-tool fail-soft
                            logger.warning(
                                "debrief_chat_read_tool_failed",
                                packet_id=self._packet_id,
                                tool=tc.get("name"),
                                error=str(exc),
                            )
                            content = "couldn't fetch that data right now"
                    messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": content}
                    )
```

- [ ] **Step 5: Swap the router's client and flip the model setting**

`backend/app/api/v2/routers/debrief_chat.py:51`: `from app.dependencies import get_anthropic_async_client` → `from app.dependencies import get_llm_client`. `:100-101`:

```python
    return DebriefChatRunner(
        client=get_anthropic_async_client(),
```

→

```python
    return DebriefChatRunner(
        llm=get_llm_client(),
```

Note in `_build_runner`'s docstring that the client is acquired **directly**, not via `Depends`, so `app.dependency_overrides` is not a seam for it — the route tests monkeypatch `_build_runner` itself, and `test_build_runner_passes_the_configured_alias` is the only test that sees the real wiring.

`backend/app/config.py:284-288`, before:

```python
    # Debrief conversation agent (chat over a generated packet). Sonnet, consistent
    # with the assistant-route + intake runtime LLMs (the strict-Opus rule governs
    # the coding agent, not in-product runtimes). MAX_ITERS bounds the in-loop read-
    # tool cycle to prevent a runaway tool loop.
    DEBRIEF_CHAT_MODEL: str = "claude-sonnet-4-6"
```

after:

```python
    # Debrief conversation agent (chat over a generated packet).
    # A GATEWAY ALIAS, not a provider model id — litellm-config.yaml maps it
    # (sonnet today). MAX_ITERS bounds the in-loop read-tool cycle to prevent a
    # runaway tool loop.
    #
    # This alias MUST resolve to a tool-capable model. llm_core.stream_turn emits
    # no tool_call event on the emulated path, so an alias without native function
    # calling does not degrade this agent, it disables it — the recruiter gets a
    # confident answer over zero retrieved data. Pinned by
    # backend/tests/services/intake/test_llm_stream.py.
    DEBRIEF_CHAT_MODEL: str = "debrief-chat"
```

- [ ] **Step 6: Prove the 11 specs were MOVED, not retyped**

A diff cannot show this: the envelope change reindents every line of all eleven specs. `PROPOSE_TOOL_SPECS` is **not** `ast.literal_eval`-able (measured — `Name(id='_PROPOSE_NOT_EXECUTED')`, plus `**` unpacking, a bare Name, a Starred list and a Subscript), so the phase-2 `exec` technique is required. `READ_TOOL_SPECS` alone *is* literal-eval-able; execute the whole module anyway so both lists are proven the same way.

Run from the repo root, **before committing**:

```bash
git show HEAD:backend/app/services/debrief_chat/tool_specs.py > /tmp/old_tool_specs.py
python3 - <<'PY'
import importlib.util, sys

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)   # exec, not literal_eval: PROPOSE_TOOL_SPECS is computed
    return mod

old = load("/tmp/old_tool_specs.py", "old_specs")
new = load("backend/app/services/debrief_chat/tool_specs.py", "new_specs")

old_all = old.READ_TOOL_SPECS + old.PROPOSE_TOOL_SPECS
new_all = new.READ_TOOL_SPECS + new.PROPOSE_TOOL_SPECS
assert len(old_all) == len(new_all) == 11, (len(old_all), len(new_all))

for o, n in zip(old_all, new_all):
    assert set(n) == {"type", "function"} and n["type"] == "function", n
    f = n["function"]
    assert set(f) == {"name", "description", "parameters"}, sorted(f)
    assert o["name"] == f["name"], (o["name"], f["name"])
    assert o["description"] == f["description"], o["name"]
    assert o["input_schema"] == f["parameters"], o["name"]
    print(f"  ok  {o['name']}")
print("11/11 specs moved with their descriptions and schemas byte-identical")
PY
rm /tmp/old_tool_specs.py
```

Paste the output in the commit body. The module is pure data with no imports beyond `__future__`, so this runs on the host interpreter with no backend package installed.

- [ ] **Step 7: Run test to verify it passes, and restart the proxy**

```bash
make test
docker compose up -d --build backend
```

Expected: `make test` PASS — **2189 passed, 5 skipped** (2180 + 9). `docker compose ps` shows `backend` healthy. No `litellm` restart is needed in this task: `debrief-chat` already exists in the running proxy.

- [ ] **Step 8: Self-review and commit**

```bash
git diff --cached
git add backend/app/services/debrief_chat backend/app/api/v2/routers/debrief_chat.py backend/app/config.py litellm-config.yaml backend/tests/services/debrief_chat backend/tests/api/v2/test_debrief_chat_route.py
git commit -m "feat(debrief-chat): rewrite the tool loop onto the llm-core gateway"
```

---

### Task 4: Rewrite the intake text loop, the coverage tracker it feeds, and their two entry points

**This is the largest task and it cannot be decomposed further.** `text_runner.py:234-240` fires `intake_core.coverage_tracker.run_coverage_tracker(anthropic_client=…)`, and that function calls `anthropic_client.messages.create(...)` and reads `response.content[0].text` (`coverage_tracker.py:80-88`). The moment `text_runner` holds an `LLMClient` instead of an `AsyncAnthropic`, the tracker gets the wrong object:

- it calls `.messages.create` on an `LLMClient` → `AttributeError`
- caught by its own `except Exception` at `:86`
- returns `{"ok": False, "error": …}` and logs `tracker_llm_failed`
- `text_runner._on_coverage_task_done` sees no exception, so nothing is logged there either

The post-turn coverage backstop dies, silently, with **no failing test** — every `text_runner` test patches `coverage_tracker_run` with an `AsyncMock`, which accepts any client and any kwargs. That is CHECKPOINT bug-shape #3 at the service level, and it is also the reason phase 3 cannot leave `get_anthropic_async_client` alive: `text_runner` is the only backend caller, so once the factory goes there is no Anthropic client to hand the tracker.

`coverage_tracker.py` is `intake-core`, which the spec assigns to phase 4, and its other caller is `voice-agent/src/main.py:2198`, which the spec assigns to phase 7. **The spec is internally inconsistent here** and already half-admits it: §Per-service migration says *"The raw `AsyncAnthropic` at `main.py:2172` migrates with the coverage tracker"* while placing the two in different phases. Phase 3 forces the issue because it is the first phase that takes the Anthropic client away from `text_runner`.

**Mitigation for the parameter rename being the safety mechanism:** rename `anthropic_client` to `llm`. A wrong *object* under the old name is silent; a wrong *keyword* is a `TypeError` raised synchronously by `coverage_tracker_run(**kwargs)` inside `run_text_turn`, which surfaces as an SSE error frame. Loud beats silent. A backend test additionally pins the signature.

**Files:**
- Modify: `intake-core/intake_core/coverage_tracker.py`
- Modify: `backend/app/services/intake/text_runner.py`
- Modify: `backend/app/api/v2/routers/intake_text_messages.py`
- Modify: `backend/app/config.py`
- Modify: `litellm-config.yaml`
- Modify: `voice-agent/Dockerfile`, `voice-agent/src/main.py`, `voice-agent/scripts/smoke_test_v2.py`
- Modify: `docker-compose.yml` (`voice-agent` gains `depends_on: [litellm]`)
- Test: `intake-core/tests/test_coverage_tracker.py`
- Test: `backend/tests/services/intake/test_text_runner.py`
- Test: `backend/tests/api/v2/test_intake_text_messages.py`

**Interfaces:**
- Consumes: `stream_llm_turn` (Task 1); `INTAKE_TOOLS_OPENAI` (Task 2); `get_llm_client`; `LLMClient.complete(*, model, messages, tools=None, system=None, max_tokens=2048, temperature=None, tool_choice=None) -> LLMReply`.
- Produces: `run_coverage_tracker(supabase_client, llm, model, session_id, last_user_turn, debounce_ms=200)` — return contract unchanged; `run_text_turn(supabase_client, llm, model, session_id, user_message)` and `run_text_opening(supabase_client, llm, model, session_id)` — event contract unchanged; new setting `INTAKE_TEXT_MODEL = "intake-text"`; new gateway alias `intake-text`.

- [ ] **Step 1: Write the failing test**

**`intake-core/tests/test_coverage_tracker.py`** — replace the Anthropic double in all ten tests. The fake stays a plain mock so `intake-core` acquires no dependency on `llm-core` (`coverage_tracker` calls a duck-typed `llm`; it imports nothing new). Before:

```python
    mock_anthropic = AsyncMock()
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text='{"q4_must_haves": {...}}')]
    )
    ...
        result = await run_coverage_tracker(
            supabase_client=mock_sb,
            anthropic_client=mock_anthropic,
            model="claude-sonnet-4-6",
            ...
        )
    mock_anthropic.messages.create.assert_called_once()
```

After:

```python
from types import SimpleNamespace

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = SimpleNamespace(text='{"q4_must_haves": {...}}')
    ...
        result = await run_coverage_tracker(
            supabase_client=mock_sb,
            llm=mock_llm,
            model="intake-text",
            ...
        )
    mock_llm.complete.assert_awaited_once()
```

Add one test:

```python
@pytest.mark.asyncio
async def test_the_tracker_sends_an_alias_and_no_tools():
    """The tracker asks for JSON in prose and parses it itself — it has never used
    tool calling, so it is unaffected by tool emulation and safe on any alias."""
    mock_sb = MagicMock()
    mock_sb.rpc = AsyncMock()
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = SimpleNamespace(text="{}")
    with patch("intake_core.coverage_tracker.aload_session",
               new=AsyncMock(return_value={"id": "s", "current_answers": {}, "turns": []})):
        await run_coverage_tracker(
            supabase_client=mock_sb, llm=mock_llm, model="intake-text",
            session_id="s", last_user_turn="hi", debounce_ms=0,
        )
    kwargs = mock_llm.complete.await_args.kwargs
    assert kwargs["model"] == "intake-text"
    assert kwargs["temperature"] == 0
    assert kwargs["max_tokens"] == 1024
    assert "tools" not in kwargs
```

**`backend/tests/services/intake/test_text_runner.py`** — mechanical changes to all 13 existing tests: `anthropic_client=MagicMock()` → `llm=MagicMock()`; every scripted `"stop_reason": "tool_use"` → `"tool_calls"`; `model="claude-sonnet-4-6"` / `model="x"` → `model="intake-text"`. `test_run_text_turn_tool_messages_appended_correctly` (`:488-546`) is **replaced** by `test_request_history_is_openai_shaped` below — its assertions on `tool_use` / `tool_result` blocks are asserting the bug this task removes.

Add seven tests. The first four run the **real** seam over `fake_llm`:

```python
import json

from llm_core.types import LLMReply, ToolCall


async def _run_over(fake_llm, session, supabase, message="Python"):
    """Drive run_text_turn through the REAL stream_llm_turn seam.

    Every other test in this file patches the seam and scripts events, which
    cannot see the messages array the second request carries — and that array is
    what this task rewrote."""
    with patch("app.services.intake.text_runner.aload_session",
               new=AsyncMock(return_value=session)), \
         patch("app.services.intake.text_runner.append_turn_for_session",
               new=AsyncMock(return_value={"idx": 0})), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"), \
         patch("app.services.intake.text_runner.ahandle_tool_call",
               new=AsyncMock(return_value={"ok": True})), \
         patch("app.services.intake.text_runner.coverage_tracker_run", new=AsyncMock()):
        return await _collect(run_text_turn(
            supabase_client=supabase, llm=fake_llm,
            model="intake-text", session_id="sess-1", user_message=message,
        ))


@pytest.mark.asyncio
async def test_request_history_is_openai_shaped(fake_session, mock_supabase, fake_llm):
    """The crux. Spec §Streaming reason 3: the old code put
    {"type": "tool_result", "tool_use_id": ...} blocks inside a {"role": "user"}
    message, which OpenAI's Chat Completions schema cannot accept at all."""
    client, _ = mock_supabase
    fake_llm.queue_reply(LLMReply(
        text="Got it. ", model="fake",
        tool_calls=[ToolCall(id="toolu_1", name="update_answer",
                             arguments={"qid": "q4_must_haves", "text": "Python",
                                        "confidence": "high"})],
        finish_reason="tool_calls",
    ))
    fake_llm.queue_text("Any other must-haves?")

    await _run_over(fake_llm, fake_session, client)

    assert len(fake_llm.calls) == 2
    second = fake_llm.calls[1]["messages"]
    assistant, tool_msg = second[-2], second[-1]

    assert assistant["role"] == "assistant"
    assert isinstance(assistant["content"], str)
    assert "tool_use" not in json.dumps(assistant)
    call = assistant["tool_calls"][0]
    assert call["id"] == "toolu_1"
    assert call["type"] == "function"
    assert call["function"]["name"] == "update_answer"
    # A JSON STRING, not the decoded dict the tool_call event carried.
    assert isinstance(call["function"]["arguments"], str)
    assert json.loads(call["function"]["arguments"])["qid"] == "q4_must_haves"

    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "toolu_1"
    assert "tool_result" not in json.dumps(tool_msg)


@pytest.mark.asyncio
async def test_the_loop_is_driven_by_tool_calls_not_by_a_stop_reason_string(
    fake_session, mock_supabase, fake_llm
):
    """Spec §Streaming reason 1, pinned. The old `!= "tool_use"` comparison exited
    after one iteration having executed nothing. A corrected string comparison
    would still break against a gateway that omits finish_reason, so the loop no
    longer reads it at all."""
    client, _ = mock_supabase
    fake_llm.queue_reply(LLMReply(
        text="", model="fake",
        tool_calls=[ToolCall(id="t1", name="update_answer",
                             arguments={"qid": "q1_role_overview", "text": "x",
                                        "confidence": "low"})],
        finish_reason=None,   # NOT "tool_calls", NOT "tool_use"
    ))
    fake_llm.queue_text("Thanks.")

    events = await _run_over(fake_llm, fake_session, client)

    assert len(fake_llm.calls) == 2
    assert [p["name"] for k, p in events if k == "tool_call"] == ["update_answer"]


@pytest.mark.asyncio
async def test_the_openai_tool_specs_reach_the_gateway(fake_session, mock_supabase, fake_llm):
    client, _ = mock_supabase
    fake_llm.queue_text("Hello.")
    await _run_over(fake_llm, fake_session, client)

    sent = fake_llm.calls[0]
    assert sent["model"] == "intake-text"
    assert {t["function"]["name"] for t in sent["tools"]} == {"update_answer", "mark_status"}
    assert all(t["type"] == "function" for t in sent["tools"])


@pytest.mark.asyncio
async def test_a_tool_call_with_no_id_still_pairs_with_its_result(
    fake_session, mock_supabase, fake_llm
):
    """stream_turn passes the provider's id through raw and it can be None. The
    seam backfills it; this asserts the assistant turn and the tool message end up
    agreeing, because a mismatch is a 400 on the NEXT request."""
    client, _ = mock_supabase
    fake_llm.queue_reply(LLMReply(
        text="", model="fake",
        tool_calls=[ToolCall(id="", name="update_answer",
                             arguments={"qid": "q1_role_overview", "text": "x",
                                        "confidence": "low"})],
        finish_reason="tool_calls",
    ))
    fake_llm.queue_text("ok")

    await _run_over(fake_llm, fake_session, client)

    second = fake_llm.calls[1]["messages"]
    assistant, tool_msg = second[-2], second[-1]
    assert assistant["tool_calls"][0]["id"]
    assert assistant["tool_calls"][0]["id"] == tool_msg["tool_call_id"]


@pytest.mark.asyncio
async def test_an_incomplete_tool_call_is_not_dispatched_or_persisted(
    fake_session, mock_supabase
):
    """CHECKPOINT fact #3 at this site. A truncated argument buffer arrives as
    input={}. intake-core would reject it as `unknown qid: None`, which is safe —
    but the runner still recorded it in the assistant turn's tool_calls, where it
    is indistinguishable from a call that worked."""
    client, _ = mock_supabase
    call_count = 0

    async def fake_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield ("tool_call", {"id": "t1", "name": "update_answer", "input": {}})
            yield ("done", {"text": "", "stop_reason": "tool_calls"})
        else:
            yield ("text", "Sorry, could you repeat that?")
            yield ("done", {"text": "Sorry, could you repeat that?", "stop_reason": "stop"})

    mock_append = AsyncMock(side_effect=[{"idx": 0}, {"idx": 1}])
    mock_tool = AsyncMock(return_value={"ok": True})

    with patch("app.services.intake.text_runner.aload_session",
               new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session", new=mock_append), \
         patch("app.services.intake.text_runner.stream_llm_turn", new=fake_stream), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"), \
         patch("app.services.intake.text_runner.ahandle_tool_call", new=mock_tool), \
         patch("app.services.intake.text_runner.coverage_tracker_run", new=AsyncMock()):
        await _collect(run_text_turn(
            supabase_client=client, llm=MagicMock(),
            model="intake-text", session_id="sess-1", user_message="Python",
        ))

    mock_tool.assert_not_awaited()
    assert call_count == 2                       # the model is told and can retry
    assert mock_append.call_args_list[1].kwargs["tool_calls"] is None


@pytest.mark.asyncio
async def test_the_coverage_tracker_receives_the_gateway_client(fake_session, mock_supabase):
    """The silent failure this task exists to prevent: the tracker calling
    .messages.create on an LLMClient, swallowing the AttributeError, and killing
    the post-turn backstop with nothing in any suite to notice."""
    client, _ = mock_supabase
    llm = MagicMock()

    async def fake_stream(**kwargs):
        yield ("done", {"text": "", "stop_reason": "stop"})

    mock_cov = AsyncMock()
    with patch("app.services.intake.text_runner.aload_session",
               new=AsyncMock(return_value=fake_session)), \
         patch("app.services.intake.text_runner.append_turn_for_session",
               new=AsyncMock(return_value={"idx": 0})), \
         patch("app.services.intake.text_runner.stream_llm_turn", new=fake_stream), \
         patch("app.services.intake.text_runner.build_dynamic_prompt", return_value="SYS"), \
         patch("app.services.intake.text_runner.coverage_tracker_run", new=mock_cov):
        await _collect(run_text_turn(
            supabase_client=client, llm=llm,
            model="intake-text", session_id="sess-1", user_message="hi",
        ))
        for _ in range(5):
            await asyncio.sleep(0)

    kwargs = mock_cov.call_args.kwargs
    assert kwargs["llm"] is llm
    assert kwargs["model"] == "intake-text"
    assert "anthropic_client" not in kwargs


def test_the_coverage_tracker_signature_cannot_drift_back():
    """text_runner spawns the tracker with **kwargs, so a parameter rename in
    intake-core would be a runtime TypeError inside an SSE stream. intake-core's
    own suite is not in this gate; this is the cheapest place the drift fails."""
    import inspect

    from intake_core.coverage_tracker import run_coverage_tracker

    params = inspect.signature(run_coverage_tracker).parameters
    assert "llm" in params
    assert "anthropic_client" not in params
```

**`backend/tests/api/v2/test_intake_text_messages.py`** — all four tests currently do:

```python
    patch("app.api.v2.routers.intake_text_messages.get_anthropic_async_client",
          return_value=MagicMock())
```

**That patch is inert.** `Depends(get_anthropic_async_client)` captured the function object at import time, so patching the module attribute does not change what FastAPI resolves — the real factory runs, reads `ANTHROPIC_API_KEY` from `conftest`, and builds a real `AsyncAnthropic` (no network, so nothing fails). Delete all four and use the override that actually works:

```python
from app.dependencies import get_llm_client
...
        app.dependency_overrides[get_supabase] = lambda: mock_supabase
        app.dependency_overrides[get_llm_client] = lambda: fake_llm
        try:
            ...
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            app.dependency_overrides.pop(get_llm_client, None)
```

(the conftest `clear_caches` fixture also clears `app.dependency_overrides` on teardown; the explicit pops keep these tests readable). Add one:

```python
def test_the_route_passes_the_configured_alias(recruiter_client, fake_llm):
    """The router used to hardcode ANTHROPIC_MODEL = "claude-sonnet-4-6"."""
    session_id = uuid4()
    captured = {}

    async def fake_gen(**kwargs):
        captured["model"] = kwargs["model"]
        captured["llm"] = kwargs["llm"]
        yield ("done", {"text": "", "stop_reason": "stop",
                        "user_turn_idx": 0, "assistant_turn_idx": 1})

    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute_async = AsyncMock(
        return_value=MagicMock(data={
            "id": str(session_id), "active_modality": None, "status": "ready",
            "user_id": RECRUITER_USER_ID, "organization_id": ORG_ID,
        })
    )

    with patch("app.api.v2.routers.intake_text_messages.require_no_other_modality", new=AsyncMock()), \
         patch("app.api.v2.routers.intake_text_messages.run_text_turn", new=fake_gen):
        app.dependency_overrides[get_supabase] = lambda: mock_supabase
        app.dependency_overrides[get_llm_client] = lambda: fake_llm
        try:
            resp = recruiter_client.post(
                f"{V2_ROOT}/intake/sessions/{session_id}/text/messages",
                json={"message": "hi"},
            )
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            app.dependency_overrides.pop(get_llm_client, None)

    assert resp.status_code == 200
    assert captured["model"] == "intake-text"
    assert captured["llm"] is fake_llm
```

**Assertions on exact text chunking must become joins where `fake_llm` drives the stream.** `FakeLLM.queue_text` and `queue_reply` split text into several deltas (`fake.py:33` — `_DELTA = re.compile(r"\s*\S+|\s+$")`), deliberately, because the real client yields once per provider chunk. `"Got it. "` streams as `["Got", " it.", " "]`. Tests that patch the seam and script events keep their exact-chunk assertions; the four `_run_over` tests must assert `"".join(text_events)` or use `queue_text_deltas` to pin a split.

- [ ] **Step 2: Run test to verify it fails**

Run: `make test`
Expected: FAIL — `TypeError: run_text_turn() got an unexpected keyword argument 'llm'`, and `AssertionError` on `"anthropic_client" not in inspect.signature(run_coverage_tracker).parameters`.

- [ ] **Step 3: Migrate the coverage tracker**

`intake-core/intake_core/coverage_tracker.py:42-49`, before:

```python
async def run_coverage_tracker(
    supabase_client,
    anthropic_client,
    model: str,
    session_id: str,
    last_user_turn: str,
    debounce_ms: int = 200,
) -> dict[str, Any]:
```

after:

```python
async def run_coverage_tracker(
    supabase_client,
    llm,
    model: str,
    session_id: str,
    last_user_turn: str,
    debounce_ms: int = 200,
) -> dict[str, Any]:
```

`:80-88`, before:

```python
    try:
        response = await anthropic_client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=0,
            system=TRACKER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
    except Exception as e:
```

after:

```python
    try:
        # `model` is a gateway alias, not a provider model id. No tools are used
        # here — the tracker asks for JSON in prose and parses it itself — so this
        # call is unaffected by tool emulation and is safe on any alias.
        reply = await llm.complete(
            model=model,
            max_tokens=1024,
            temperature=0,
            system=TRACKER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = reply.text
    except Exception as e:
```

Update the module docstring line 4: `"Calls Sonnet 4.6, parses the patch,"` → `"Calls the LLM gateway, parses the patch,"`. **Note that this module imports nothing new** — `llm` is duck-typed, so `intake-core` gains no dependency on `llm-core`.

Also update `:52-53`'s docstring to name `llm` instead of the Anthropic client, and add:

```python
    """Run a single coverage tracker pass. Returns {ok, applied, patch?, error?}.

    `llm` is a provider-agnostic client with `.complete(...)` — llm_core.LLMClient
    in both live callers. The parameter was `anthropic_client` before phase 3, and
    it was RENAMED rather than repurposed on purpose: passing the wrong client
    under the old name would have failed as an AttributeError swallowed by the
    except below, killing this backstop with nothing anywhere to notice. A wrong
    keyword is a loud TypeError at the call site instead.
    ...
    """
```

- [ ] **Step 4: Move the voice agent's tracker onto the gateway**

Forced by Step 3 and by the spec's own *"the raw `AsyncAnthropic` at `main.py:2172` migrates with the coverage tracker"*. `voice-agent/src/main.py:43`'s `ALL_TOOLS` import and the pipecat service are **untouched** — that is phase 7.

`voice-agent/Dockerfile`, after the `intake-core` install block (`:28-29`):

```dockerfile
# llm-core is the shared gateway client. The intake coverage tracker moved onto
# it in phase 3, and this container is one of its two callers. The pipecat LLM
# service is still Anthropic-bound — that is phase 7.
COPY llm-core /tmp/llm-core
RUN pip install --no-cache-dir /tmp/llm-core && rm -rf /tmp/llm-core
```

`voice-agent/src/main.py:2172-2176`, before:

```python
    from anthropic import AsyncAnthropic
    tracker_anthropic = AsyncAnthropic(api_key=settings.voice_anthropic_api_key)
    tracker_model = os.getenv("ANTHROPIC_MODEL_SONNET", "claude-sonnet-4-6")

    tracker_model_ref = tracker_model
```

after:

```python
    # The coverage tracker runs through the LiteLLM gateway (phase 3). `llm_core`
    # is imported here rather than at module scope because `get_client()`
    # constructs its HTTP client on first call, and this module is imported by
    # tooling that has no gateway configured.
    from llm_core import get_client as get_llm_client

    tracker_llm = get_llm_client()
    tracker_model_ref = "voice-intake"   # a gateway alias, not a provider model id
```

`:2198-2203`, before:

```python
        intake_on_user_turn=lambda text, idx: run_coverage_tracker(
            supabase_client=sb,
            anthropic_client=tracker_anthropic,
            model=tracker_model_ref,
```

after:

```python
        intake_on_user_turn=lambda text, idx: run_coverage_tracker(
            supabase_client=sb,
            llm=tracker_llm,
            model=tracker_model_ref,
```

`voice-agent/scripts/smoke_test_v2.py:75-88`: replace the `AsyncAnthropic` construction and `await ant.close()` with `llm = get_llm_client()` and `llm=llm, model="voice-intake"`; drop the `try/finally` (the gateway client is a process singleton and is not closed per call). Update the `[6]` print from `"live Anthropic call"` to `"live gateway call"`.

`docker-compose.yml`, the `voice-agent` block (`:11-26`): add `depends_on: [litellm]` beside `extra_hosts`. `env_file: [.env]` already supplies `LLM_GATEWAY_URL` and `LITELLM_MASTER_KEY` (`.env.example:129,131`), so no new variable is introduced.

- [ ] **Step 5: Rewrite `text_runner.py`**

`:21-27`, before:

```python
from intake_core.coverage_tracker import run_coverage_tracker as coverage_tracker_run
from intake_core.persistence import aload_session
from intake_core.prompts.builder import build_dynamic_prompt
from intake_core.tools import INTAKE_TOOLS_ANTHROPIC, ahandle_tool_call

from app.services.intake.anthropic_stream import stream_llm_turn
from app.services.intake.turn_writer import append_turn_for_session
```

after:

```python
from intake_core.coverage_tracker import run_coverage_tracker as coverage_tracker_run
from intake_core.persistence import aload_session
from intake_core.prompts.builder import build_dynamic_prompt
from intake_core.tools import INTAKE_TOOLS_OPENAI, ahandle_tool_call

from app.services.intake.llm_stream import stream_llm_turn
from app.services.intake.turn_writer import append_turn_for_session
```

and add `import json` to the stdlib imports.

After `_MAX_TOOL_ITERATIONS = 5` (`:31`), add:

```python
# What each tool must carry to be a real call. A truncated argument buffer arrives
# as input={} (llm_core client.py:436-449). intake-core would refuse it as
# "unknown qid: None", which is safe — but the refusal is unnamed, unlogged, and
# the call was still recorded on the assistant turn as though it had worked.
_REQUIRED_ARGS = {
    spec["function"]["name"]: frozenset(
        spec["function"]["parameters"].get("required") or []
    )
    for spec in INTAKE_TOOLS_OPENAI
}


def _missing_args(tool_call: dict[str, Any]) -> frozenset[str]:
    supplied = set((tool_call.get("input") or {}).keys())
    return _REQUIRED_ARGS.get(tool_call.get("name"), frozenset()) - supplied
```

Rename `_format_turns_for_anthropic` (`:74`) to `_format_turns_for_llm`, update both call sites (`:123`, `:246`) and its docstring line 1 to `"""Convert stored turns into gateway messages format."""`. Its body is already OpenAI-valid and does not change.

Rename the `anthropic_client` parameter to `llm` in both `run_text_opening` (`:92`) and `run_text_turn` (`:186`), and update the three uses: `:157` `client=anthropic_client` → `llm=llm`; `:236` `anthropic_client=anthropic_client` → `llm=llm`; `:258` `client=anthropic_client` → `llm=llm`.

Module docstring `:3`: `"Streams an Anthropic Sonnet turn back to the caller"` → `"Streams one assistant turn back to the caller through the LLM gateway"`.

`:262` `tools=INTAKE_TOOLS_ANTHROPIC,` → `tools=INTAKE_TOOLS_OPENAI,`.

**The loop rewrite.** `:273-343`, before:

```python
        # Build the assistant content block list for history
        assistant_content: list[dict[str, Any]] = []
        if iteration_text_parts:
            assistant_content.append({
                "type": "text",
                "text": "".join(iteration_text_parts),
            })
        for tc in iteration_tool_calls:
            assistant_content.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc.get("input", {}),
            })

        messages.append({"role": "assistant", "content": assistant_content})

        if final_stop_reason != "tool_use":
            # Terminal stop — exit the loop
            break

        if iteration == _MAX_TOOL_ITERATIONS - 1:
            logger.warning(
                "tool_use_loop_guard_hit",
                session_id=session_id,
                iterations=_MAX_TOOL_ITERATIONS,
            )
            break

        # Execute tool calls, collect results, append tool_result turn
        tool_results_content: list[dict[str, Any]] = []
        for tc in iteration_tool_calls:
            tool_name = tc.get("name")
            try:
                result = await ahandle_tool_call(
                    supabase_client=supabase_client,
                    session_id=session_id,
                    tool_call=tc,
                    turn_idx=user_turn["idx"],
                )
                all_tool_calls.append({
                    "name": tool_name,
                    "args": tc.get("input", {}),
                })
                yield ("tool_call", tc)
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": str(result) if result is not None else "ok",
                })
            except Exception as e:
                logger.warning(
                    "tool_call_failed",
                    session_id=session_id,
                    name=tool_name,
                    error=str(e),
                )
                all_tool_calls.append({
                    "name": tool_name,
                    "args": tc.get("input", {}),
                })
                yield ("tool_call", tc)
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": f"error: {e}",
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results_content})
        # Continue to next iteration — LLM generates follow-up
```

after:

```python
        # OpenAI-shaped assistant turn: `content` is a STRING, the calls live in a
        # sibling `tool_calls` array, and `arguments` is a JSON string rather than
        # the decoded dict the tool_call event carried. Both empty forms are
        # omitted rather than sent as null / [] — some providers behind the
        # gateway reject them.
        assistant: dict[str, Any] = {"role": "assistant"}
        iteration_text = "".join(iteration_text_parts)
        if iteration_text or not iteration_tool_calls:
            assistant["content"] = iteration_text
        if iteration_tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("input") or {}),
                    },
                }
                for tc in iteration_tool_calls
            ]
        messages.append(assistant)

        # The loop is driven by WHETHER CALLS ARRIVED, not by a stop_reason string.
        # This was `if final_stop_reason != "tool_use": break`, and stream_turn
        # passes the provider's finish_reason through untouched — so the value is
        # "tool_calls" here, and None from a gateway that never sends one. The
        # comparison failed on the first tool-using turn and the loop exited after
        # one iteration having executed nothing, with no error. Correcting the
        # string would leave the same class of bug in place; the presence of calls
        # is what this loop actually depends on. final_stop_reason is still
        # reported in the `done` payload.
        if not iteration_tool_calls:
            break

        if iteration == _MAX_TOOL_ITERATIONS - 1:
            logger.warning(
                "tool_use_loop_guard_hit",
                session_id=session_id,
                iterations=_MAX_TOOL_ITERATIONS,
                stop_reason=final_stop_reason,
            )
            break

        # One {"role": "tool"} message PER CALL, each naming the id it answers.
        # Every entry in the assistant turn's tool_calls must be answered before
        # the next assistant turn or the gateway 400s. This was a single
        # {"role": "user"} message holding every tool_result block, which OpenAI's
        # schema cannot accept at all.
        for tc in iteration_tool_calls:
            tool_name = tc.get("name")
            missing = _missing_args(tc)
            if missing:
                # A degraded call is not dispatched, is not yielded to the caller,
                # and is NOT recorded on the assistant turn — recording it would
                # make a call that did nothing indistinguishable from one that
                # worked. Naming the absent properties lets the model retry.
                logger.warning(
                    "intake_tool_arguments_incomplete",
                    session_id=session_id,
                    name=tool_name,
                    missing=sorted(missing),
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": (
                        "that call was missing required properties: "
                        f"{', '.join(sorted(missing))}"
                    ),
                })
                continue

            try:
                result = await ahandle_tool_call(
                    supabase_client=supabase_client,
                    session_id=session_id,
                    tool_call=tc,
                    turn_idx=user_turn["idx"],
                )
                content = str(result) if result is not None else "ok"
            except Exception as e:
                logger.warning(
                    "tool_call_failed",
                    session_id=session_id,
                    name=tool_name,
                    error=str(e),
                )
                content = f"error: {e}"

            all_tool_calls.append({"name": tool_name, "args": tc.get("input") or {}})
            yield ("tool_call", tc)
            messages.append(
                {"role": "tool", "tool_call_id": tc["id"], "content": content}
            )
        # Continue to next iteration — the model generates its follow-up
```

Behaviour deliberately preserved: a tool that *raises* still yields its `tool_call` event and is still recorded in `all_tool_calls`, exactly as before — only the `is_error` flag disappears, because OpenAI tool messages have no equivalent field and the message text already says `error:`.

- [ ] **Step 6: Rewrite the router, add the setting and the alias**

`backend/app/api/v2/routers/intake_text_messages.py`:

- `:34` `from app.dependencies import get_anthropic_async_client` → `from app.dependencies import get_llm_client`, and add `from app.config import get_settings`.
- `:46`, before `ANTHROPIC_MODEL = "claude-sonnet-4-6"` → **delete the constant.** Replace its two uses (`:75`, `:167`) with `model=get_settings().INTAKE_TEXT_MODEL`.
- `:67`, `:101`, `:160`, `:186` — the parameter and kwarg renames: `anthropic_client` → `llm`, `anthropic=Depends(get_anthropic_async_client)` → `llm=Depends(get_llm_client)`, `anthropic_client=anthropic` → `llm=llm`.

`backend/app/config.py`, immediately after `INTAKE_JD_MODEL` (`:182`):

```python
    # Intake TEXT conversation agent (the streaming tool loop) and the post-turn
    # coverage tracker it fires. A GATEWAY ALIAS, not a provider model id —
    # litellm-config.yaml maps it (sonnet today, matching the claude-sonnet-4-6
    # the router hardcoded before phase 3).
    #
    # This alias MUST resolve to a tool-capable model. llm_core.stream_turn emits
    # no tool_call event on the emulated path, so an alias without native function
    # calling does not degrade this agent, it disables it — the recruiter's answers
    # would silently never be persisted and the emulated JSON would be streamed to
    # them as chat prose. Pinned by
    # backend/tests/services/intake/test_llm_stream.py.
    #
    # Distinct from `voice-intake` even though both drive the same intake persona:
    # the text path streams through llm_core and the voice path through pipecat
    # (phase 7), and two aliases let either be repointed at a local model
    # independently.
    INTAKE_TEXT_MODEL: str = "intake-text"
```

`litellm-config.yaml`, beside the other sonnet entries:

```yaml
  # STREAMING TOOL LOOP — supports_function_calling MUST stay true. See the
  # comment on debrief-chat; a false here silently stops the intake agent
  # persisting any answer at all.
  #
  # Sonnet, because backend/app/api/v2/routers/intake_text_messages.py hardcoded
  # claude-sonnet-4-6 before phase 3. This alias also serves the post-turn
  # coverage tracker on the text path; the voice path uses voice-intake.
  - model_name: intake-text
    litellm_params:
      model: anthropic/claude-sonnet-5
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info: {supports_function_calling: true}
```

**What the frontend sees.** The SSE `done` payload's `stop_reason` changes vocabulary — `"end_turn"` becomes `"stop"`. Verified safe: `recruiter-app/src/lib/intake/api.ts:474` passes it through as `d.stop_reason ?? null` and `src/types/intake.ts:277` types it `string | null`; nothing in `recruiter-app` branches on the value. The `'end_turn'` occurrences in `recruiter-app` are fixtures inside its own tests, not assertions about backend behaviour, so its suite is unaffected and no `npm run build` is required.

*(Review note: the spec's stated recruiter-app count of 1224 is stale. Measured on merged
`main` 2026-08-10: **1273 tests, 1271 pass, 2 fail**. The 2 failures are pre-existing and
flaky — `src/components/shell/composer.test.tsx` passes 6/6 in isolation and only fails under
full-suite parallelism. Do not treat them as a phase-3 regression; see CHECKPOINT.md.)*

- [ ] **Step 7: Run every affected suite**

```bash
make test
cd intake-core && python -m pytest -q && cd ..
docker compose up -d --build backend voice-agent
docker compose up -d litellm            # the new intake-text alias
make verify
```

Expected: `make test` PASS — **2198 passed, 5 skipped** (2189 + 9). `intake-core` PASS, +1 over Task 2's count. `make verify` shows `ok backend`, `ok litellm`, `ok voice-agent`. **Paste all three results.** `voice-agent` has no automated test covering Step 4 — `make verify` is its only gate, and the commit must say so rather than imply coverage that does not exist.

- [ ] **Step 8: Self-review and commit**

```bash
git diff --cached
git add backend/app/services/intake/text_runner.py backend/app/api/v2/routers/intake_text_messages.py backend/app/config.py litellm-config.yaml docker-compose.yml intake-core/intake_core/coverage_tracker.py intake-core/tests/test_coverage_tracker.py voice-agent backend/tests/services/intake/test_text_runner.py backend/tests/api/v2/test_intake_text_messages.py
git commit -m "feat(intake): rewrite the text agent loop and its coverage tracker onto the gateway"
```

---

### Task 5: Delete `anthropic_stream.py`

Its last importer moved in Task 4. Verify that before deleting anything.

**Files:**
- Delete: `backend/app/services/intake/anthropic_stream.py`
- Delete: `backend/tests/services/intake/test_anthropic_stream.py`

**Interfaces:** none. This task removes code only.

- [ ] **Step 1: Prove nothing imports it**

```bash
grep -rn "anthropic_stream" --include="*.py" backend/ intake-core/ voice-agent/ workers/
```

Expected: matches **only** in `backend/app/services/intake/anthropic_stream.py`, `backend/tests/services/intake/test_anthropic_stream.py` and the docstring of `backend/tests/test_anthropic_surface.py`. If any other file appears, a previous task is incomplete — stop and finish it.

- [ ] **Step 2: Delete both files**

```bash
git rm backend/app/services/intake/anthropic_stream.py backend/tests/services/intake/test_anthropic_stream.py
```

**The suite count falls by 2 here, and this is the one place in the phase where it legitimately may.** The rule is that a count may only fall when the module under test is deleted, and then only by that module's own tests, with a named replacement. Both conditions hold: `test_anthropic_stream.py` contains exactly 2 tests, both of which assert the behaviour of a module that no longer exists, and the replacement (`test_llm_stream.py`, 11 tests) landed in Task 1 and covers the same tagged contract plus two normalizations the old module never had. Coverage is unaffected in the aggregate because the ~50 statements being uncovered are being deleted with their tests.

- [ ] **Step 3: Run test to verify it passes**

Run: `make test`
Expected: PASS — **2196 passed, 5 skipped** (2198 − 2).

- [ ] **Step 4: Self-review and commit**

```bash
git diff --cached
git commit -m "refactor(intake): delete anthropic_stream now that both loops stream through llm-core"
```

---

### Task 6: The coordinated deletion — the factory, the pin, and the test that exists to fail until now

`backend/tests/test_anthropic_surface.py` was written in phase 2 specifically to fail at this moment. Its own docstring says so: *"Phase 3 empties `_EXPECTED_CLIENT_USERS`, deletes the factory, drops the pin, and deletes this file."* The two entries in `_EXPECTED_CLIENT_USERS` are the two routers Tasks 3 and 4 migrated, so `test_only_the_streaming_routers_still_take_the_anthropic_client` is already red by the time this task starts — that is the signal that the phase is complete, not a defect.

The three deletions must land together. Dropping the pin while the factory survives breaks `backend/app/dependencies.py` at import, taking the whole application with it.

**Files:**
- Modify: `backend/app/dependencies.py`
- Modify: `backend/requirements.txt`
- Modify: `intake-core/pyproject.toml` — **added in review; the plan as written missed this
  and its own verification step would have failed because of it.** `intake-core`
  pins `anthropic>=0.40,<1.0` at `:9`, and intake-core is installed into the backend image,
  so removing only the backend pin leaves the SDK installed and importable. Safe to drop
  here and *only* here: `coverage_tracker.py` was intake-core's sole consumer (verified —
  `grep -rn anthropic intake-core/intake_core/` returns just `:44` and `:81`, both inside
  that one function), it never even imported the SDK (the client arrives as a duck-typed
  parameter), and Task 4 has already migrated it by this point.
- Delete: `backend/tests/test_anthropic_surface.py`
- Modify: `backend/tests/api/test_dependencies_extra.py`
- Create: `backend/tests/test_no_provider_sdk.py`

**Interfaces:**
- Removes: `app.dependencies.get_anthropic_async_client`, `app.dependencies._anthropic_client`, the `_AsyncAnthropic` and `_os` imports, and `anthropic>=0.40.0`.
- Produces: `backend/tests/test_no_provider_sdk.py`, which pins the *end state* rather than a transitional one.

- [ ] **Step 1: Prove the factory has no consumers**

```bash
grep -rn "get_anthropic_async_client\|from anthropic import\|^import anthropic" --include="*.py" backend/
```

Expected: matches only in `backend/app/dependencies.py`, `backend/tests/test_anthropic_surface.py` and `backend/tests/api/test_dependencies_extra.py`. Anything else means a task above is incomplete.

- [ ] **Step 2: Write the replacement test**

Create `backend/tests/test_no_provider_sdk.py`. **Every property `test_anthropic_surface.py` guarded is carried over**; two are strengthened (they now assert an empty set rather than an allowlist) and one is added (the requirements pin), so nothing is retired without a replacement:

```python
"""No provider SDK reaches this backend. Phase 3's end state, pinned.

Replaces test_anthropic_surface.py, which existed to fail until the streaming
path migrated. Every property it guarded is here; the two that carried an
allowlist of surviving Anthropic consumers now assert the empty set, and one is
new — that the SDK is gone from requirements.txt, not merely unimported.

These are SOURCE-TEXT assertions, not import checks, on purpose: a regression
here is someone TYPING the old shape back into a module, and that has to fail in
this suite rather than at runtime against a provider.

Deliberately NOT asserted: that the string "anthropic" is absent from
backend/app. candidate_detection_service.py and recall_webhook/end_state.py POST
raw httpx to api.anthropic.com and read settings.ANTHROPIC_API_KEY. They import
no SDK, they belong to no phase in the current rollout, and they are out of
scope — see the spec's six-surface inventory, which does not list them.
"""

from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_APP = _BACKEND / "app"


def _modules_containing(needle: str) -> set[str]:
    return {
        path.relative_to(_APP).as_posix()
        for path in _APP.rglob("*.py")
        if needle in path.read_text(encoding="utf-8")
    }


def test_no_module_imports_the_anthropic_sdk():
    assert _modules_containing("from anthropic import") == set()
    assert _modules_containing("import anthropic") == set()


def test_the_anthropic_client_factory_is_gone():
    assert _modules_containing("get_anthropic_async_client") == set()


def test_the_anthropic_pin_is_gone_from_requirements():
    """Unimported is not uninstalled. The pin's removal is what makes the image
    stop shipping the SDK, and it is the half of the deletion a source grep over
    app/ cannot see."""
    requirements = (_BACKEND / "requirements.txt").read_text(encoding="utf-8")
    assert "anthropic" not in requirements


def test_no_module_speaks_the_anthropic_messages_api():
    """Both halves: .messages.create was the non-streaming call, .messages.stream
    the streaming one. Phase 2 removed the first; phase 3 removed the second."""
    assert _modules_containing(".messages.create(") == set()
    assert _modules_containing(".messages.stream(") == set()


def test_no_module_carries_an_anthropic_tool_spec():
    """llm_core rejects `input_schema` rather than translating it, on the native
    path as well as the emulated one — but at CALL time, and several call sites
    sit behind seams their own tests mock. Failing here means it cannot reach a
    running system."""
    assert _modules_containing("input_schema") == set()


def test_no_module_passes_an_anthropic_shaped_tool_choice():
    assert _modules_containing('{"type": "tool", "name"') == set()


def test_no_module_reads_a_tool_call_positionally():
    """Forcing guarantees the named tool IS called — not that it is the ONLY call.
    Measured against anthropic/claude-sonnet-5 through the live gateway: a forced
    request returned [forced_tool, second_tool]. Every site therefore reads via
    LLMReply.tool_call_named or by matching the streamed event's `name`."""
    assert _modules_containing("tool_calls[") == set()
```

In `backend/tests/api/test_dependencies_extra.py`, delete `test_get_anthropic_async_client_singleton` (`:198-207`, including its section banner) and drop `get_anthropic_async_client` from the module docstring at `:4`. That is the phase's second and last legitimate test deletion: the function it tests no longer exists, and its replacement property — that the factory is gone entirely — is `test_the_anthropic_client_factory_is_gone` above.

- [ ] **Step 3: Run test to verify it fails**

Run: `make test`
Expected: FAIL — `test_no_module_imports_the_anthropic_sdk` reports `{'dependencies.py'}`, and `test_the_anthropic_pin_is_gone_from_requirements` fails on the pin.

- [ ] **Step 4: Delete the factory**

`backend/app/dependencies.py:211-234`, before:

```python
# Anthropic async client — singleton at app scope.
# FastAPI/uvicorn runs a single event loop for the lifetime of the process,
# so a module-level AsyncAnthropic instance is safe here.
#
# STILL ALIVE ON PURPOSE after the phase-2 migration. Its only remaining
# consumers are the two STREAMING routers (intake_text_messages, debrief_chat),
# which phase 3 rewrites onto llm_core.stream_turn. Non-streaming call sites use
# get_llm_client() instead; see backend/tests/test_anthropic_surface.py, which
# fails if a new consumer appears. Phase 3 deletes this block, that test, and the
# `anthropic` pin in requirements.txt together.

import os as _os
from anthropic import AsyncAnthropic as _AsyncAnthropic

_anthropic_client: "_AsyncAnthropic | None" = None


def get_anthropic_async_client() -> "_AsyncAnthropic":
    """FastAPI dependency that returns a process-scoped AsyncAnthropic client."""
    global _anthropic_client
    if _anthropic_client is None:
        api_key = _os.environ["ANTHROPIC_API_KEY"]
        _anthropic_client = _AsyncAnthropic(api_key=api_key, max_retries=2)
    return _anthropic_client


# LLM gateway client — the provider-agnostic path. Provider choice lives in
# litellm-config.yaml, so nothing below this line names a provider.
```

after — the whole block is removed, and the comment introducing `get_llm_client` absorbs the history:

```python
# LLM gateway client — the provider-agnostic path and now the ONLY one. Provider
# choice lives in litellm-config.yaml, so nothing in this file names a provider.
#
# get_anthropic_async_client lived here until phase 3. Its last two consumers were
# the streaming routers, which now stream through llm_core.stream_turn; the
# `anthropic` pin left requirements.txt in the same commit. See
# backend/tests/test_no_provider_sdk.py, which fails if either grows back.
```

`import os as _os` goes with it — it has exactly one use, at the deleted `:232`.

- [ ] **Step 5: Drop the pin**

`backend/requirements.txt:10-14`, before:

```
# Streaming only. The nine non-streaming call sites moved to the LiteLLM gateway
# via llm-core in phase 2; text_runner and debrief_chat/runner still stream
# through the Anthropic SDK until phase 3 rewrites them. Dropping this pin before
# then breaks two routers at import.
anthropic>=0.40.0
```

after — all five lines are deleted. No replacement comment: the absence of a provider SDK is the design, and `test_no_provider_sdk.py` says so where it can fail.

`backend/tests/conftest.py`'s `ANTHROPIC_API_KEY` stays. `candidate_detection_service.py:142` and `recall_webhook/end_state.py:223` still read `settings.ANTHROPIC_API_KEY` for their raw httpx POSTs, and `test_end_state.py:168` and `test_cal_intel_detection.py:167` still set it.

- [ ] **Step 6: Delete the transitional test**

```bash
git rm backend/tests/test_anthropic_surface.py
```

**Arithmetic.** `test_anthropic_surface.py` holds exactly **6** tests (`test_only_the_streaming_routers_still_take_the_anthropic_client`, `test_the_anthropic_sdk_is_imported_in_exactly_one_place`, `test_no_migrated_module_still_speaks_the_anthropic_message_api`, `test_only_the_streaming_tool_specs_still_use_input_schema`, `test_no_module_reads_a_tool_call_positionally`, `test_no_module_passes_an_anthropic_shaped_tool_choice`). Step 2 deletes 1 more from `test_dependencies_extra.py` and adds 7 in `test_no_provider_sdk.py`. Net: **−6 −1 +7 = 0**, so the suite stays at **2196 passed, 5 skipped**, which is baseline + 29.

- [ ] **Step 7: Run test to verify it passes, and rebuild the stack**

```bash
make test
docker compose up -d --build backend
make verify
```

Expected: `make test` PASS — **2196 passed, 5 skipped**, `--cov-fail-under=85` satisfied. `make verify` shows `ok backend` and `ok litellm`. Confirm the SDK really left the image:

```bash
docker compose exec backend python -c "import anthropic" ; echo "exit=$?"
```

Expected: `ModuleNotFoundError` and a non-zero exit.

**If you get a zero exit, do NOT assume the image was not rebuilt** — that was this step's
original diagnosis and it sends you chasing a Docker caching problem that is not there.
Check `intake-core/pyproject.toml:9` first. It pins `anthropic>=0.40,<1.0`, intake-core is
installed into the backend image, and that pin alone keeps the SDK importable no matter what
`backend/requirements.txt` says. The source-text tests in this task CANNOT see it — they
scan files, not the installed environment, so they will happily pass while the SDK is still
in the image. Dropping that pin is part of this task's Files list above. Only after
confirming it is gone is "the image was not rebuilt" the right conclusion.

- [ ] **Step 8: Live-verify both streaming paths (recommended, ~2 billed calls)**

`make test` proves neither loop regressed against a fake; it cannot prove the rewritten request history is one the gateway accepts, and *that* is the failure mode this phase was written to remove. It only appears on turn two, which is exactly the turn a fake cannot exercise against a real provider.

Using the e2e sandbox account, drive one intake text turn that provokes a tool call ("The must-haves are Python and Postgres") and one debrief chat turn that provokes a read tool ("where did Ada's score come from?"). For each, confirm from `docker compose logs backend`:

- a second `chat/completions` request was issued (the loop iterated — the old code would have exited after one),
- no `llm_stream_tool_call_id_backfilled`, `intake_tool_arguments_incomplete`, `debrief_chat_propose_arguments_incomplete` or `llm_stream_tools_emulated` warning,
- for intake: `update_answer_applied` from intake-core, and `tracker_applied` or `tracker_llm_failed` from the coverage tracker — the tracker line is the one that proves Task 4's cross-package change actually works, and it is the single least-covered thing in this phase.

Record the result in the phase ledger. If this step is skipped, say so — do not let its absence read as a pass.

- [ ] **Step 9: Self-review and commit**

```bash
git diff --cached
git add backend/app/dependencies.py backend/requirements.txt backend/tests/test_no_provider_sdk.py backend/tests/api/test_dependencies_extra.py
git commit -m "refactor(backend): drop the Anthropic SDK, its client factory, and its transitional pin"
```

- [ ] **Step 10: Update the checkpoint**

In `.superpowers/sdd/CHECKPOINT.md`: mark phase 3 **DONE**, set the suite baseline to 2196/5, and add to HARD-WON FACTS:

1. `stream_turn` yields tool calls as `('tool_call', {"id", "name", "input"})` — the key is **`input`**, not `arguments`, and **`id` can be `None`**. `llm_stream.stream_llm_turn` backfills the id; nothing else may assume it is present.
2. **The emulated-tools path cannot carry a streaming tool loop at all** — no `tool_call` event is ever emitted. Both streaming aliases are pinned tool-capable in two places (`LLM_FORCE_JSON_TOOLS` at runtime, `litellm-config.yaml` statically). llm-core still has no public capability accessor; adding one is the cheap follow-up that would let a runner refuse a config-level emulated alias too.
3. **The debrief service has 11 tools, not 12.** Phase 1's hazard note and the phase-3 brief both say 12.
4. **`intake_core.coverage_tracker` moved in phase 3, not phase 4** — `text_runner` is one of its two callers and could not keep an Anthropic client past this phase. `voice-agent/src/main.py:2172` and `voice-agent/Dockerfile` moved with it. Phase 4's remaining intake-core scope is `tools/schemas.py` (make the OpenAI form canonical, delete `_as_openai_tool` and `ALL_TOOLS`) and `screening/tools.py`; phase 7's is smaller by the tracker.
5. `intake-core` has its own 80+ test suite that **`make test` does not run**. Any phase touching `intake-core/intake_core/` must run `cd intake-core && python -m pytest -q` and paste the count.

---

## Definition of done for this plan

- `make test` green at **2196 passed, 5 skipped**, `--cov-fail-under=85` satisfied. Baseline + 29. Skips unchanged.
- `cd intake-core && python -m pytest -q` green, +4 over its pre-phase count, with the count pasted in Tasks 2 and 4.
- `grep -rn "from anthropic import\|^import anthropic" backend/` returns nothing; `grep -n anthropic backend/requirements.txt` returns nothing; `docker compose exec backend python -c "import anthropic"` fails with `ModuleNotFoundError`.
- `grep -rn "get_anthropic_async_client" backend/` returns nothing.
- `grep -rn "input_schema" backend/app` returns nothing. (It still returns two hits under `intake-core/`, which is phase 4's, and they are what still feeds voice-agent.)
- `grep -rn "tool_use\|tool_result" backend/app` returns nothing — neither loop constructs an Anthropic content block, and neither compares a stop reason against `"tool_use"`.
- Both loops are driven by the presence of tool calls, not by a `stop_reason` string. Pinned by `test_the_loop_continues_on_tool_calls_not_on_a_stop_reason_string` and `test_the_loop_is_driven_by_tool_calls_not_by_a_stop_reason_string`, each of which scripts `finish_reason=None`.
- Both loops build OpenAI request history: an assistant message with a string `content`, a sibling `tool_calls` array carrying `"type": "function"` and **JSON-string** `arguments`, followed by one `{"role": "tool", "tool_call_id": ...}` message per call. Pinned by `test_request_history_is_openai_shaped` in both runner suites, both of which read `fake_llm.calls[1]["messages"]` through the **real** seam rather than a patched one.
- All 11 debrief tool specs are `{"type": "function", "function": {...}}` and were proven **moved, not retyped**, by `exec`-ing both revisions and asserting `description` and `input_schema`/`parameters` equality per spec — `exec` because `PROPOSE_TOOL_SPECS` is not `literal_eval`-able. The intake-core pair is proven by object identity (`is`), which is stronger.
- Both streaming aliases (`intake-text`, `debrief-chat`) exist in `litellm-config.yaml` and declare `supports_function_calling: true`; the seam additionally refuses either at runtime if it appears in `LLM_FORCE_JSON_TOOLS`.
- Two settings hold aliases (`DEBRIEF_CHAT_MODEL`, new `INTAKE_TEXT_MODEL`); no streaming site hardcodes a provider model id. `voice-intake` is no longer an orphan alias.
- Every empty-arguments landing site from the table above is either safe-by-construction or guarded on the tool schema's `required` set, with a distinct log event. The one dangerous site — a `propose_*` call with `input={}` becoming a persisted confirm card — cannot happen.
- `docker compose up -d --build backend voice-agent && docker compose up -d litellm && make verify` shows `ok backend`, `ok litellm`, `ok voice-agent`.
- `.superpowers/sdd/CHECKPOINT.md` updated: phase 3 DONE, baseline 2196/5, five new hard-won facts, and the phase-4/phase-7 scope reductions recorded.
- Untouched by this phase, as intended: `backend/app/services/candidate_detection_service.py` and `backend/app/services/recall_webhook/end_state.py` (raw httpx to `api.anthropic.com`, no SDK, no phase); `intake_core/screening/tools.py` and `intake_core/tools/schemas.py`'s Anthropic exports (phase 4); `voice-agent`'s pipecat service and its `ALL_TOOLS` import (phase 7); every prompt string in the repo.

## Carried forward

- **llm-core has no public capability accessor.** `CapabilityCache` is reachable only through the private `LLMClient._caps`, so the runtime emulation guard covers `LLM_FORCE_JSON_TOOLS` and not `model_info: {supports_function_calling: false}`. The static config test covers the second, but only for aliases someone remembered to list. Adding `LLMClient.supports_tools(alias)` is additive and cheap.
- **`stream_turn` has no `tool_choice`, and the reason is the emulated-path gap** — see `tool-choice-report.md` §1. Neither streaming site wants forcing, so nothing is blocked today. If one ever does, the gap has to be closed first.
- **A nameless streamed tool call raises `LLMError` out of `run_text_turn`** after the user turn has already been persisted, leaving an orphan user turn and no assistant turn. Pre-existing, not introduced here, and not fixed here.
- **Phase 1 hazard #3 is now half-live.** `voice-agent/src/pipeline/turn_persist.py:99,162` filter persisted transcripts by matching Anthropic content-block types, and `text_runner._format_turns_for_llm` replays voice-written history into the text agent. Phase 3 did not change what voice writes, so nothing is broken yet — but phase 7 will, and whichever of the two lands second owes the other a replay check.
- **`.env.example:148` lists `LLM_FORCE_JSON_TOOLS=intake-jd-local,smoke-local,gemma-local`.** Neither streaming alias is there, which is why the runtime guard is currently inert. That is the correct state; it is recorded so nobody "helpfully" adds one during local-model evaluation.
- **`litellm-config.yaml`'s `request_timeout: 120` with `num_retries: 2` still cannot fit inside the 60s client budget** (phase 1 hazard #4). Untouched, and it now governs two streaming paths as well.
