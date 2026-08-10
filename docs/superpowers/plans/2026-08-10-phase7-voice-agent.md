# `voice-agent` LLM Migration Implementation Plan (Phase 7 — FINAL)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the last provider SDK out of the last service. `voice-agent`'s pipecat pipeline stops constructing `AnthropicLLMService` with `settings.voice_anthropic_api_key` and constructs `OpenAILLMService(base_url=<gateway>, api_key=<master key>, model=<alias>)` instead, so that after this phase `grep -rn "anthropic" voice-agent/src voice-agent/requirements.txt` returns nothing, `docker compose exec voice-agent python -c "import anthropic"` raises `ModuleNotFoundError`, and no application module anywhere in the repo holds a provider API key — only `litellm-config.yaml` does.

**Architecture:** The swap is cheap *because phases 3 and 4 already did the hard parts*. `factory.py` is on pipecat's **universal** `LLMContext` / `LLMContextAggregatorPair` / `ToolsSchema` stack, which both services consume through per-provider adapters; the shared `messages` list is already OpenAI-shaped whichever service is attached; `register_function` lives on the shared `LLMService` base; `tool_schemas.py` (phase 4 Task 1) already emits `FunctionSchema` objects that the OpenAI adapter renders back into exactly the OpenAI tool shape. What is left is a constructor swap at one factory function, five `PipelineConfig(...)` sites, and the settings behind them. The risk is not the framework — it is the two places where `OpenAILLMService` *behaves differently from* `AnthropicLLMService` on a degraded reply, both verified line by line below and both invisible to this repo's test suite because every voice conftest stubs pipecat into `sys.modules`.

**Tech Stack:** Python 3.11, pipecat-ai 0.0.102 (`openai` 2.52.0, core dep), `llm-core` (installed into the voice image since phase 3), `intake-core`, LiteLLM proxy, FastAPI, aiortc/SmallWebRTC, pytest (explicit `@pytest.mark.asyncio` outside the backend), Docker Compose.

**Source spec:** `docs/superpowers/specs/2026-08-07-provider-agnostic-llm-design.md` (§Per-service migration row for `voice-agent`, line 207)
**Prior phase:** `docs/superpowers/plans/2026-08-10-phase5-6-workers.md` (COMPLETE)
**Live state:** `.superpowers/sdd/CHECKPOINT.md` — **BINDING, and it supersedes the spec wherever they disagree.**
**Recon:** `.superpowers/sdd/phases-4-7-recon.md` §PHASE 7 + B11/B12/B16 — every claim re-verified against source and against the installed pipecat at HEAD `5eaaaa5`. Corrections listed in "What recon and the spec got wrong".

---

## SCOPE — what phase 7 is NOT

- **The raw `AsyncAnthropic` is ALREADY GONE.** The spec's row names `voice-agent/src/pipeline/services.py:39` *and* `main.py:2172`. Phase 3 migrated the second one with the coverage tracker. Verified at HEAD: `main.py:2176` is `from llm_core import get_client as get_llm_client`, `:2178` `tracker_llm = get_llm_client()`, `:2179` `tracker_model_ref = "voice-intake"`, and `main.py:2284-2287` documents why the client is deliberately not closed per session. `grep -rn "AsyncAnthropic\|from anthropic import" voice-agent/` returns **nothing**. **Do not re-plan it.** Task 1 Step 0 re-confirms it rather than trusting this paragraph.
- **`scripts/smoke_test_v2.py` is already on the gateway** (`:80-92`, `llm_core.get_client()` + alias `voice-intake`). Only its stale usage docstring at `:11` (`export ANTHROPIC_API_KEY=...`) is phase 7's, and it is a one-line fix inside Task 2.
- **No prompt text changes.** A spec non-goal. `build_voice_intake_prompt`, `build_voice_screening_prompt`, `generate_persona`, `generate_intake_persona` are untouched.
- **No tool-schema changes.** Phase 4 made the OpenAI shape canonical; `voice-agent/src/pipeline/tool_schemas.py` is the one tested reader and it does not change.
- **`intake-core`, `llm-core`, and the three workers are not touched.** Their suites are re-run as regression gates only.

---

## Recon's three "no blocker" claims — each verified INDEPENDENTLY

Recon (B16) rested the whole phase on three claims. All three are **TRUE**. The evidence, and the two caveats recon did not surface:

| # | claim | verdict | evidence |
|---|---|---|---|
| 1 | Both services are already on the universal `LLMContext` / `ToolsSchema` stack, consumed via adapters | **TRUE** | `LLMService.adapter_class: Type[BaseLLMAdapter] = OpenAILLMAdapter` (`pipecat/services/llm_service.py:177`) is the default; `AnthropicLLMService` overrides it (`pipecat/services/anthropic/llm.py:119`). Both `_process_context` bodies accept `OpenAILLMContext \| LLMContext` (`anthropic/llm.py:378`, `openai/base_llm.py:360`) and both route a universal context through `adapter.get_llm_invocation_params(context)`. `OpenAILLMAdapter._from_universal_context_messages` (`adapters/services/open_ai_adapter.py:113-124`) is a **pass-through** — the universal message list already *is* the OpenAI format, which is why `TurnPersistFrameProcessor`, `InterruptContextCleaner` and `refresh_system_prompt` are unaffected. `LLMContext.__init__` stores `self._messages = messages` **by reference** (`processors/aggregators/llm_context.py:131`), so the factory's shared `messages` list keeps working identically. |
| 2 | `base_url` is supported | **TRUE** | `BaseOpenAILLMService.__init__(*, model, api_key=None, base_url=None, …)` — `openai/base_llm.py:91-104`, forwarded to `create_client` at `:138-145` and into `AsyncOpenAI(base_url=base_url, …)` at `:169-180`. `OpenAILLMService.__init__` (`openai/llm.py:72-86`) is `(*, model, params, **kwargs)` and passes `**kwargs` straight through, so `base_url` and `api_key` arrive as kwargs. |
| 3 | `openai` is a **core** pipecat dependency, so no `[openai]` extra is needed | **TRUE, and provable from metadata rather than inference** | `pipecat_ai-0.0.102.dist-info/METADATA` contains `Requires-Dist: openai<3,>=1.74.0` **with no extra marker**, versus `Requires-Dist: anthropic~=0.49.0; extra == "anthropic"`. The `Provides-Extra: openai` that does exist adds only `pipecat-ai[websockets-base]`, which is for the **Realtime** service, not `OpenAILLMService`. In the running image: `openai 2.52.0`, `Required-by: llm-core, pipecat-ai`. |

**Caveat recon missed on claim 1:** the adapter is a pass-through for *messages*, but **not** for tool specs. `OpenAILLMAdapter.to_provider_tools_format` (`open_ai_adapter.py:70-84`) rebuilds each tool from `FunctionSchema.to_default_dict()` (`adapters/schemas/function_schema.py:41-55`), which emits exactly `{"name", "description", "parameters": {"type": "object", "properties", "required"}}`. Any key our specs carry *inside* `parameters` other than `type`/`properties`/`required` is silently dropped. Our two intake specs and one screening spec carry only those, so this is a no-op today — but it is a real constraint on future schemas and Task 1 pins it.

**Caveat recon missed on claim 3:** dropping the `[anthropic]` extra is what actually removes `anthropic 0.49.0` from the image. Recon called keeping it "harmless". It is not harmless — it leaves a provider SDK installed in the last service that was supposed to stop having one, and it is the only thing standing between this phase and a clean `import anthropic → ModuleNotFoundError` check.

---

## The real behaviour differences — what a caller would notice

Everything below was read in the installed pipecat 0.0.102 inside `openrecruiting-voice-agent:latest`, not inferred.

**Unchanged (verified, so they are not risks):** context aggregation (both use the same `LLMContextAggregatorPair` from `llm_response_universal`), system-prompt handling (OpenAI leaves `role: "system"` in the message list, which is where `refresh_system_prompt` already writes it; the Anthropic adapter *extracts* it — so if anything the OpenAI path is the simpler one), `register_function` (`llm_service.py:504`, shared base, `factory.py:225` unchanged), streaming text frames (both call `self._push_llm_text` → `LLMTextFrame`, `llm_service.py:370-382`), interruption (both inherit `_handle_interruptions` and `cancel_on_interruption`), the tool-call *event* shape reaching our handler (`FunctionCallParams.arguments` is a parsed dict either way), and the recorded turn shape in `messages` (`{"role":"assistant","tool_calls":[…]}` + `{"role":"tool","tool_call_id":…}`, written by the universal aggregator regardless of service).

| # | difference | Anthropic today | OpenAI after the swap | consequence | task |
|---|---|---|---|---|---|
| 1 | **A tool call arriving with EMPTY arguments** | `anthropic/llm.py:474` — `args = json.loads(json_accumulator) if json_accumulator else {}`. The call is **still dispatched**, with `{}`. `dispatch_tool_call` → `handle_update_answer(args={})` → `_validate_args` returns `"unknown qid: None"` → `{"ok": False, "error": …}` goes back through `params.result_callback`, and the model can see it failed and retry. | `openai/base_llm.py:464` — `if function_name and arguments:` guards appending the final tool call. `arguments == ""` is falsy, so the call is **never appended**, `run_function_calls([])` returns immediately (`llm_service.py:625-626`), no handler runs, no result callback fires, no `FunctionCallsStartedFrame` is broadcast, and nothing is logged. | **This is CHECKPOINT fact #3 in its voice form, and it is a regression the swap introduces.** The recruiter says the answer; the model tries to record it; the call evaporates; the assistant's next line says "Got it" and the transcript reads as if the answer was captured, while `intake_sessions.current_answers` stays blank. Today the same degradation produces a visible `ok: False`. | 3 |
| 2 | **`max_tokens`** | `AnthropicLLMService.InputParams.max_tokens` defaults to **4096** (`anthropic/llm.py:162`) and is always sent (`:410`). | `BaseOpenAILLMService.InputParams.max_tokens` and `max_completion_tokens` both default to `NOT_GIVEN` (`openai/base_llm.py:86-87`), so **neither is sent** and LiteLLM's own default applies to the Anthropic upstream. | Silent change to the realtime path's truncation point — and truncation is the main cause of difference #1. Must be set explicitly to 4096 so the swap is a real no-op. | 2 |
| 3 | **Malformed (partial) tool arguments** | The `FunctionCallFromLLM` is only built when `stop_reason == "tool_use"` arrives (`anthropic/llm.py:466-478`); a truncated turn stops with a different reason and no call is built. | `openai/base_llm.py:475` runs `json.loads(arguments)` on the accumulated string **outside** any per-call try, so one malformed call raises, is caught at `:524-525` (`push_error(f"Error during completion: {e}")`), and **every** tool call in that turn is lost — plus an `ErrorFrame` is pushed into the pipeline that nothing in `voice-agent` handles. | Blast radius widens from one call to the whole turn. Same guard as #1 covers detection. | 3 |
| 4 | **Prompt caching** | `services.py:43` `InputParams(enable_prompt_caching=True)` → `_with_cache_control_markers` in the Anthropic adapter. | No equivalent. | Cost and TTFT on long personas. **The spec accepts this loss explicitly** (§Risks, spec line 278). Recorded, not fixed. | — |
| 5 | **Completion timeout** | `anthropic/llm.py:540` calls the `on_completion_timeout` event handler only. | `openai/base_llm.py:522-523` calls the handler **and** `push_error("LLM completion timeout")`. | An extra `ErrorFrame` on the timeout path. Nothing in this pipeline consumes `ErrorFrame`, so the practical effect is a log line — noted so it is not read as a new bug during verification. | — |
| 6 | **`tools` when a pipeline has none** | Adapter returns `[]` (`anthropic_adapter.py:71`). | Adapter returns `context.tools` unchanged, which is `openai._types.NOT_GIVEN` (`llm_context.py:25-26, 46-47, 121`) — the openai SDK omits the field. | **No difference in practice.** Checked because a pipecat-local `NotGiven` would have serialised into the request body and broken the three tool-less pipelines. It is openai's. | — |

---

## The degraded-reply question, per site (CHECKPOINT fact #3)

Six instances have been found in this codebase. Phase 7 touches one live conversational path; traced to its end:

| # | site | what a degraded/empty reply produces | verdict | task |
|---|---|---|---|---|
| 1 | Model returns **no text and no tool call** at all | `_process_context` emits `LLMFullResponseStartFrame` … `LLMFullResponseEndFrame` with nothing between. No `LLMTextFrame` → no TTS → **the bot goes silent** and stays silent until the recruiter speaks again or the 30-minute timer at `main.py:2299-2309` injects a wrap-up. `TurnPersistFrameProcessor._conversation` skips empty text (`turn_persist.py:169-171`), so nothing is written and nothing is logged. Identical today and after the swap. | **PRE-EXISTING and unguarded.** Not a fabricated answer, but a completely silent failure on the one path a human is waiting on in real time. | 3 |
| 2 | Tool call dropped for empty/malformed arguments (differences #1 and #3 above) | Nothing dispatched, nothing persisted, and the model's *next* turn is generated from a context in which the tool "succeeded" as far as it can tell. The transcript reads as a captured answer; `current_answers` is blank. | **DANGEROUS, and introduced by this phase.** Same family as the fabricated `likely_authentic` verdict from phase 2. | 3 |
| 3 | Context summarization returns an empty summary | `llm_service.py:494-495` — `if not summary_text: raise RuntimeError("LLM returned empty summary")`. Pipecat's own guard, present on both services. `OpenAILLMService.run_inference` returns `response.choices[0].message.content`, which is `None` when the model produces nothing → the guard fires. | **already guarded, by pipecat.** Recorded so it is not mistaken for an omission. | — |
| 4 | Coverage tracker (phase 3's, still live at `main.py:2201-2207`) | `parse_tracker_response` returns `{}` → `{"ok": True, "applied": False}`. | **safe by construction**, verified in phase 4 recon §4a.3. Untouched. | — |

**Task 3 is the answer to #1 and #2.** We cannot patch pipecat's dropped-call branch without vendoring 100 lines of its internals, and a fork of `_process_context` would rot on the next pipecat bump. What we *can* own is making the silence audible: a processor that watches one LLM turn and logs a named event when it produced **neither** text **nor** a recognised tool call. `FunctionCallsStartedFrame` is broadcast only when `len(function_calls) > 0` (`llm_service.py:625-631`), which makes it the exact signal for "a tool call survived", and `LLMFullResponseEndFrame` is pushed from the `finally` (`base_llm.py:526-528`) so the check fires even on the error path.

---

## Call-site inventory

`PipelineConfig(...)` is constructed at **five** sites. Recon (B11) said `main.py:489, 706, 1230, 1846, **2178**`; the last one moved to **2181** when phase 3 inserted the `llm_core` block above it. The `anthropic_api_key=` kwarg lines are `491, 708, 1232, 1848, 2183` — the brief's list is correct and is what a grep finds.

| # | File | `PipelineConfig(` | `anthropic_api_key=` | pipeline | tools? | shape |
|---|---|---|---|---|---|---|
| 1 | `voice-agent/src/main.py` | `:489` | `:491-492` | v1 feedback | no | plain: deepgram + persona + context/flux knobs |
| 2 | `voice-agent/src/main.py` | `:706` | `:708-709` | v1 intake | no | identical to #1 |
| 3 | `voice-agent/src/main.py` | `:1230` | `:1232-1233` | feedback v2 (RTVI) | no | #1 + `rtvi_processor` + `transcript_accumulator` |
| 4 | `voice-agent/src/main.py` | `:1846` | `:1848-1849` | screening | **yes** — `tools=ALL_SCREENING_TOOLS` (`:1859`) | + `intake_tool_dispatch`, `prompt_refresh`, `transcript_accumulator` |
| 5 | `voice-agent/src/main.py` | `:2181` | `:2183-2184` | v2 intake | **yes** — `tools=INTAKE_TOOLS` (`:2195`) | + `seed_messages`, `intake_session_id`, `intake_supabase_client`, `intake_tool_dispatch`, `intake_on_user_turn` (coverage tracker), `intake_initial_turn_idx` |

**Three shapes, not five**, and all five read the same two settings, so one rename reaches all of them. The only shape that matters for this migration is "tools or no tools": sites 4 and 5 exercise `function_schemas()` → `ToolsSchema` → the adapter → the wire, and sites 1-3 send `NOT_GIVEN`.

| # | File | What changes | Task |
|---|---|---|---|
| 1 | `voice-agent/src/pipeline/services.py` | `create_anthropic_llm` → `create_gateway_llm`; `AnthropicLLMService` → `OpenAILLMService(base_url=…, api_key=…)`; explicit `max_tokens=4096`; `enable_prompt_caching` dropped | 2 |
| 2 | `voice-agent/src/pipeline/factory.py` | `PipelineConfig.anthropic_api_key` / `.anthropic_model` → `llm_base_url` / `llm_api_key` / `llm_model`; `:19` and `:81-84` follow; `_make_tool_handler` reports dispatches to the empty-turn detector | 2, 3 |
| 3 | `voice-agent/src/main.py` | five `PipelineConfig(...)` sites (`:489, 706, 1230, 1846, 2181`); the log line at `:426` | 2, 4 |
| 4 | `voice-agent/src/config.py` | `voice_anthropic_api_key` (`:20`) **deleted** — the last provider credential in this codebase; `voice_anthropic_model` (`:21`) → three alias settings; `anthropic_model_sonnet` (`:45`) **deleted**, it has had zero readers since phase 3 | 2, 4 |
| 5 | `voice-agent/requirements.txt` | `pipecat-ai[anthropic,deepgram,webrtc]` → `pipecat-ai[deepgram,webrtc]` | 2 |
| 6 | `voice-agent/tests/screening/conftest.py` | `:46-47` `pipecat.services.anthropic{,.llm}` → `pipecat.services.openai{,.llm}`; `:16` `"anthropic"` stub removed | 2 |
| 7 | `voice-agent/tests/pipeline/test_llm_service.py` | **new** — pins what the factory hands the service | 1 |
| 8 | `voice-agent/scripts/smoke_llm_service.py` | **new** — the only verification that touches the real pipecat class | 1, 2 |
| 9 | `voice-agent/scripts/smoke_test_v2.py` | `:11` stale `export ANTHROPIC_API_KEY=...` | 2 |
| 10 | `voice-agent/src/pipeline/empty_turn.py` + its test | **new** — difference #1/#2's guard | 3 |
| 11 | `voice-agent/src/pipeline/tool_dispatch.py`, `turn_persist.py` | stale "Anthropic" docstrings (`:1`, `:99`) | 2 |
| 12 | `litellm-config.yaml` | `voice-screening`, `voice-feedback` added; `voice-intake`'s tier documented (B12) | 4 |
| 13 | `backend/app/services/candidate_detection_service.py`, `backend/app/services/recall_webhook/end_state.py` | the last two raw `api.anthropic.com` POSTs in the repo | 5 |
| 14 | `backend/app/config.py` | `ANTHROPIC_API_KEY` (`:113`), `VOICE_ANTHROPIC_API_KEY`/`VOICE_ANTHROPIC_MODEL` (`:175-176`, **zero readers**) | 5 |
| 15 | `backend/tests/test_no_provider_sdk.py` | its documented exclusion (`:13-17`) is retired; gains the repo-wide credential guard | 5 |
| 16 | `voice-agent/Dockerfile`, `voice-agent/build-with-intake-core.sh` | stale phase-7 comment; the EC2 build path does not stage `llm-core` | 6 |

---

## Global Constraints

- **Backend must stay at ≥ 2186 passed / 5 skipped** (`make test`, repo root, `--cov-fail-under=85`). Tasks 1-4 and 6 touch **no** backend file, so the number must be *exactly* 2186/5 after each. **Task 5 is the only task allowed to move it, and only UP.** A drop means a test was deleted rather than replaced.
- **Other suites, run exactly as this table says — the invocation matters:**

  | suite | command | current |
  |---|---|---|
  | voice-agent | `cd voice-agent && PYTHONPATH=/Users/nitinbhat/PycharmProjects/OpenRecruiting/intake-core python3 -m pytest -q` | **68 passed, 0 failed** |
  | backend | `make test` (repo root) | **2186 passed, 5 skipped** |
  | intake-core | `cd intake-core && python3 -m pytest -q` | **83 passed** |
  | llm-core | `cd llm-core && python3 -m pytest -q` | **199 passed, 12 deselected** |
  | intake-agent | `cd workers/intake-agent && python3 -m pytest -q` | **17 passed** |

- **⚠️ THE PYTHONPATH IS NOT OPTIONAL.** This host has **another project's** `intake_core` installed — `import intake_core` on a bare host resolves to `/Users/nitinbhat/PycharmProjects/MazleAI/intake-core`. `voice-agent/` has no local copy, so it loses. Running the voice suite without `PYTHONPATH` produced a *reproducible* false failure that an earlier CHECKPOINT revision wrote up as a product decision about the agent's persona. **If a voice test fails on prompt text, check the PYTHONPATH before you check the code.**
- **Unit tests CANNOT catch a real pipecat incompatibility, and this plan must not pretend otherwise.** Every `voice-agent/tests/*/conftest.py` stubs pipecat into `sys.modules` (`tests/pipeline/conftest.py:86-90` force-registers; `tests/intake/conftest.py:21-23` and `tests/screening/conftest.py:55-56` use `setdefault`). `FunctionSchema`, `OpenAILLMService`, `LLMContext` and `ToolsSchema` are all `MagicMock` under test. The suite can prove *this repo's* wiring — which kwargs the factory passes, which module names are imported — and nothing at all about whether pipecat accepts them. See "Verification reality" below.
- **`intake-core` and `llm-core` are baked into the voice image** (`voice-agent/Dockerfile:28-29, 34-35`). Rebuild with `docker compose up -d --build voice-agent` after any task that changes them or `src/`, or the container imports a stale copy (CHECKPOINT fact #4).
- **`make verify` must show `ok voice-agent`** after Task 2 and again at the end — as a **smoke check only**. `factory.create_pipeline` runs *only* when a WebRTC peer connects, so `/health` stays green forever with a broken constructor. This is the same trap phase 4 documented; do not present `make verify` as verification of the swap.
- Commit after each task with a meaningful message. **Self-review the diff before committing** (`git diff --cached`).
- No API keys, secrets, certs, or `.env` files may be committed. `ANTHROPIC_API_KEY` stays in `.env` **because the litellm container reads it** (`docker-compose.yml` litellm `env_file: [.env]`, `litellm-config.yaml` `api_key: os.environ/ANTHROPIC_API_KEY` ×21). That is the one legitimate holder.
- Every HTML element added anywhere in this project must carry a unique `id`. (No UI is added by this plan; the rule is project-wide.)
- No Next.js app is touched, so no `npm run build` is required.

---

## Verification reality — state it plainly, in every commit

Ranked by strength. The plan requires the top three; the fourth may be impossible here and the commit must say so rather than imply it was done.

1. **`voice-agent/scripts/smoke_llm_service.py` run INSIDE the rebuilt container** (Task 1 creates it; Task 2 runs it after). This is the only check that touches the real `OpenAILLMService`, the real `OpenAILLMAdapter`, the real `FunctionSchema`/`ToolsSchema`, real `register_function`, and the real gateway. It builds the tool payload exactly as `factory.create_pipeline` does and issues **one real streaming completion** through the alias, asserting a `tool_calls` delta arrives with parseable arguments. Because it is written in Task 1 and run against the **current Anthropic service first**, it produces a genuine before/after rather than a test written to pass.
2. **`docker compose exec voice-agent python -c "import anthropic"` must raise `ModuleNotFoundError`**, and `pip show openai` must still report 2.52.0. Unimported is not uninstalled — this is the half no source grep can see (phase 3 lost a debugging cycle to exactly this).
3. **The unit suite at 68 → 68 + new tests.** It proves our wiring and our guards, nothing about pipecat.
4. **A live WebRTC voice session** — the only thing that exercises interruption, TTFT, TTS timing and the tool loop end to end. It needs a browser, a microphone, a real Supabase intake session and a human listening. **This may not be verifiable in this environment. If it is not run, the Task 2 commit body must say so in those words** and the phase must not claim the realtime path was validated. `scripts/smoke_test_v2.py` is *not* a substitute: it never constructs a pipecat service.

---

## Model alias map

| Site | Model source today | Value today | Becomes | Alias |
|---|---|---|---|---|
| v1 feedback (`main.py:492`) | `settings.voice_anthropic_model` (`config.py:21`) | `claude-sonnet-4-5-20250929` | `settings.voice_feedback_model` | **`voice-feedback`** (new, Task 4) |
| v1 intake (`:709`) | same | same | `settings.voice_intake_model` | `voice-intake` (`litellm-config.yaml:121`) |
| feedback v2 (`:1233`) | same | same | `settings.voice_feedback_model` | **`voice-feedback`** (new) |
| screening (`:1849`) | same | same | `settings.voice_screening_model` | **`voice-screening`** (new) |
| v2 intake (`:2184`) | same | same | `settings.voice_intake_model` | `voice-intake` |

**B12 is real and must be documented, not smuggled.** `voice-intake` resolves to `anthropic/claude-sonnet-5` (`litellm-config.yaml:121-125`) while the voice path runs `claude-sonnet-4-5-20250929` today, and `.env` does not override `VOICE_ANTHROPIC_MODEL`. That is the same deliberate version bump phases 1-3 applied everywhere else — but `voice-intake` is one of only two entries in the whole config file with **no comment above it**, so nothing records the tier it has to preserve. Task 4 writes that comment. The tier (sonnet) is preserved; the version is upgraded on purpose.

**Why three aliases and not one.** All five sites read one knob today, which means voice screening cannot be pointed at a local model without dragging voice intake with it — and "a workload can be repointed independently" *is* the deliverable of this migration (spec §Architecture). This is the same call phases 2 and 4 made (`context-parse-jd` vs `context-synthesize`, `persona-reduce` split out of `screening-generator`). All three new aliases resolve to the same model, so Task 4 changes no behaviour; it changes what is *possible*. It is a separate task precisely so it can be reverted without touching the swap.

---

## Suite arithmetic

| after task | suite | change | expected |
|---|---|---|---|
| baseline | voice-agent | — | **68 passed** |
| baseline | backend | — | **2186 passed, 5 skipped** |
| 1 | voice-agent | + `test_llm_service.py` (5) | 73 |
| 2 | voice-agent | rewritten in place (conftest + kwarg names) | 73 |
| 3 | voice-agent | + `test_empty_turn.py` (4) | 77 |
| 4 | voice-agent | + 1 (three settings carry three distinct aliases) | 78 |
| 5 | backend | 2 files rewritten; replacements are 1-for-1 plus 2 new guards | **≥ 2188 / 5** |
| 6 | — | no test change | — |

**Every count here was derived by reading source. None was run — this is a planning document.** The executor pastes measured counts; where a measured baseline differs, the measured value wins and CHECKPOINT is corrected.

---

## File Structure

| Path | Change | Task |
|---|---|---|
| `voice-agent/tests/pipeline/test_llm_service.py` | **new** — 5 tests | 1 |
| `voice-agent/scripts/smoke_llm_service.py` | **new** — the real-class harness | 1 |
| `voice-agent/src/pipeline/services.py` | `create_gateway_llm` replaces `create_anthropic_llm` | 2 |
| `voice-agent/src/pipeline/factory.py` | config fields renamed; detector wired | 2, 3 |
| `voice-agent/src/main.py` | five sites + one log line | 2, 4 |
| `voice-agent/src/config.py` | provider credential deleted; three alias settings | 2, 4 |
| `voice-agent/requirements.txt` | `[anthropic]` extra dropped | 2 |
| `voice-agent/tests/screening/conftest.py` | stub list follows the import | 2 |
| `voice-agent/src/pipeline/empty_turn.py` | **new** | 3 |
| `voice-agent/tests/pipeline/test_empty_turn.py` | **new** — 4 tests | 3 |
| `litellm-config.yaml` | 2 aliases added, 1 documented | 4 |
| `backend/app/services/candidate_detection_service.py` | `httpx` → `llm_core` | 5 |
| `backend/app/services/recall_webhook/end_state.py` | `httpx` → `llm_core` | 5 |
| `backend/app/config.py` | three dead/retired settings | 5 |
| `backend/tests/test_no_provider_sdk.py` | exclusion retired; repo-wide guard added | 5 |
| `voice-agent/Dockerfile`, `voice-agent/build-with-intake-core.sh` | comment + EC2 build path | 6 |

---

### Task 1: Record the baseline, pin what the factory must hand the service, and build the harness BEFORE the swap

Task 2 changes the class the entire realtime path runs on. **Nothing in this repo would notice** — no test imports `src.pipeline.services` or `src.pipeline.factory` (`grep -rn "services\|factory" voice-agent/tests/` returns only two docstring mentions in `test_tool_dispatch.py`). This task closes what it can close cheaply and, more importantly, writes the harness while the *old* service is still live, so the harness records a real before/after instead of being written to make the new code pass.

**Files:**
- Create: `voice-agent/tests/pipeline/test_llm_service.py`
- Create: `voice-agent/scripts/smoke_llm_service.py`

**Interfaces:** consumes `src.pipeline.services` and `src.pipeline.factory`; produces no runtime code.

- [ ] **Step 0: Record the baselines and re-confirm the scope claims**

```bash
cd voice-agent && PYTHONPATH=/Users/nitinbhat/PycharmProjects/OpenRecruiting/intake-core python3 -m pytest -q
grep -rn "AsyncAnthropic\|from anthropic import" /Users/nitinbhat/PycharmProjects/OpenRecruiting/voice-agent/ ; echo "exit=$?"
grep -rn "anthropic" /Users/nitinbhat/PycharmProjects/OpenRecruiting/voice-agent/src --include="*.py"
```

Expected: **68 passed**; the `AsyncAnthropic` grep returns nothing (phase 3 already migrated `main.py:2172` — if it returns anything, **stop and report**, the scope section is wrong); the third grep returns exactly the ten lines listed in the inventory. Paste all three into the task notes. **Do not build on an unrecorded baseline.**

- [ ] **Step 1: Write the failing test**

Create `voice-agent/tests/pipeline/test_llm_service.py`:

```python
"""What the pipeline factory must hand its LLM service.

READ THIS BEFORE TRUSTING THIS FILE. Every conftest under voice-agent/tests
stubs pipecat into sys.modules, so OpenAILLMService here is a MagicMock. These
tests can prove which kwargs THIS REPO passes and which modules it imports.
They can prove NOTHING about whether pipecat accepts them, whether the gateway
answers, or whether a tool call survives the round trip. That is what
scripts/smoke_llm_service.py exists for, and it only runs inside the built
image against a live gateway.

The properties pinned here are the ones a wrong swap would break silently:

* the service is constructed with a GATEWAY base_url, never a provider host;
* no provider API key is read anywhere in src/ (the whole point of phase 7);
* the tool specs reach the service through tool_schemas.function_schemas, so
  the phase-4 reader stays the single tested path;
* `parameters` carries only the three keys FunctionSchema.to_default_dict()
  round-trips (name/description/parameters{type,properties,required}) — any
  other key inside `parameters` is dropped by pipecat's OpenAI adapter
  (adapters/services/open_ai_adapter.py:70-84) with no error.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

for _name in (
    "pipecat",
    "pipecat.adapters",
    "pipecat.adapters.schemas",
    "pipecat.adapters.schemas.function_schema",
    "pipecat.adapters.schemas.tools_schema",
    "pipecat.services",
    "pipecat.services.deepgram",
    "pipecat.services.deepgram.flux",
    "pipecat.services.deepgram.flux.stt",
    "pipecat.services.deepgram.tts",
    "pipecat.services.openai",
    "pipecat.services.openai.llm",
):
    sys.modules.setdefault(_name, MagicMock())

_SRC = Path(__file__).resolve().parents[2] / "src"


def _source(relative: str) -> str:
    return (_SRC / relative).read_text(encoding="utf-8")


def test_no_module_under_src_names_a_provider_sdk_or_host():
    """The phase-7 deliverable, asserted as source text rather than an import
    check, because a regression here is someone TYPING the old client back in."""
    offenders = {
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if "AnthropicLLMService" in path.read_text(encoding="utf-8")
        or "api.anthropic.com" in path.read_text(encoding="utf-8")
    }
    assert offenders == set()


def test_no_module_under_src_reads_a_provider_credential():
    offenders = {
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if "voice_anthropic_api_key" in path.read_text(encoding="utf-8")
        or "ANTHROPIC_API_KEY" in path.read_text(encoding="utf-8")
    }
    assert offenders == set()


def test_the_service_factory_is_given_a_gateway_base_url():
    """A base_url that is not the gateway means the swap moved egress rather
    than removing it."""
    text = _source("pipeline/services.py")
    assert "base_url" in text
    assert "api.anthropic.com" not in text
    assert "api.openai.com" not in text


def test_the_factory_passes_the_gateway_fields_not_a_provider_key():
    text = _source("pipeline/factory.py")
    assert "anthropic_api_key" not in text
    assert "anthropic_model" not in text
    assert "llm_base_url" in text and "llm_api_key" in text and "llm_model" in text


def test_tool_specs_still_reach_the_service_through_the_phase4_reader():
    """factory.py must not grow a second inline reader. Phase 4 collapsed four
    of them into tool_schemas.py and that has to stay the one path."""
    text = _source("pipeline/factory.py")
    assert "from src.pipeline.tool_schemas import" in text
    assert 't["name"]' not in text
    assert "input_schema" not in text
```

- [ ] **Step 2: Run it and record which assertions fail at HEAD**

```bash
cd voice-agent && PYTHONPATH=/Users/nitinbhat/PycharmProjects/OpenRecruiting/intake-core python3 -m pytest -q tests/pipeline/test_llm_service.py
```
Expected: **2 failures at HEAD** — `test_no_module_under_src_reads_a_provider_credential` (`config.py:20`) and `test_the_factory_passes_the_gateway_fields_not_a_provider_key` (`factory.py:33-34`) — plus `test_the_service_factory_is_given_a_gateway_base_url`. Three passing (`AnthropicLLMService` lives in `services.py`, so the first test also fails; confirm the exact split and record it — the point is that the file fails *for the reasons the swap will fix*, not that a specific number fails). **If any test passes for the wrong reason, fix the test before continuing.**

Because these tests fail at HEAD, this task **cannot be committed on its own with a green suite**. Mark them `@pytest.mark.xfail(reason="phase 7 Task 2 makes these pass", strict=True)` for this commit and **remove the markers in Task 2**. `strict=True` means the suite fails if they start passing early — which is what keeps them honest.

- [ ] **Step 3: Write the harness — the only check that touches real pipecat**

Create `voice-agent/scripts/smoke_llm_service.py`:

```python
"""Exercise the REAL pipecat LLM service against the REAL gateway.

Run inside the built container, where pipecat is actually installed:

    docker compose exec voice-agent python scripts/smoke_llm_service.py

Why this file exists. voice-agent's unit suite stubs pipecat into sys.modules,
so it cannot fail on a pipecat incompatibility — and factory.create_pipeline
runs only when a WebRTC peer connects, so `make verify` cannot either. Between
those two blind spots sits the entire phase-7 change. This script closes the gap
for everything except audio: it builds the service the factory builds, hands it
the tool specs the factory hands it, asks pipecat's own adapter to render the
request, and sends exactly that request to the gateway.

What it does NOT cover, and must not be claimed to: WebRTC transport, STT/TTS,
interruption, turn timing. Only a live voice session covers those.
"""

from __future__ import annotations

import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, ".")


async def main() -> int:
    from intake_core.tools import INTAKE_TOOLS
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from pipecat.processors.aggregators.llm_context import LLMContext

    from src.config import get_settings
    from src.pipeline.services import create_gateway_llm       # Task 2 renames it
    from src.pipeline.tool_schemas import function_schemas

    settings = get_settings()

    print("[1] Constructing the service the factory constructs...")
    llm = create_gateway_llm(model=settings.voice_intake_model)
    print(f"    {type(llm).__module__}.{type(llm).__name__}  model={llm.model_name}")

    print("[2] Building the context the factory builds...")
    messages = [
        {"role": "system", "content": "You are Scout. Record what the recruiter tells you."},
        {"role": "user", "content": "The role is a Staff Backend Engineer on the payments team."},
    ]
    tools_schema = ToolsSchema(standard_tools=function_schemas(INTAKE_TOOLS))
    context = LLMContext(messages, tools=tools_schema)

    print("[3] Registering the tool handlers the factory registers...")
    seen: list[str] = []

    async def _probe(params):
        seen.append(params.function_name)
        await params.result_callback({"ok": True})

    from src.pipeline.tool_schemas import tool_name

    for spec in INTAKE_TOOLS:
        llm.register_function(tool_name(spec), _probe)
    print(f"    registered: {sorted(n for n in llm._functions if n)}")

    print("[4] Rendering the request through pipecat's own adapter...")
    params_from_context = llm.get_llm_adapter().get_llm_invocation_params(context)
    request = llm.build_chat_completion_params(params_from_context)
    tools = request.get("tools") or []
    assert tools, "the adapter produced no tools — the pipeline would be toolless"
    for tool in tools:
        fn = tool["function"]
        assert fn["parameters"]["properties"], f"{fn['name']} reached pipecat with NO properties"
        assert fn["parameters"]["required"], f"{fn['name']} reached pipecat with NO required list"
    print(f"    model={request['model']}  tools={[t['function']['name'] for t in tools]}")
    print(f"    max_tokens={request.get('max_tokens')!r}")

    print("[5] One live streaming call through the gateway...")
    saw_tool, saw_text, arguments = False, False, ""
    stream = await llm.get_chat_completions(params_from_context)
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.tool_calls:
            saw_tool = True
            call = delta.tool_calls[0]
            if call.function and call.function.arguments:
                arguments += call.function.arguments
        elif delta and delta.content:
            saw_text = True
    print(f"    saw_tool_call={saw_tool} saw_text={saw_text} arg_chars={len(arguments)}")

    if not saw_tool:
        print("FAIL: the alias returned no tool call. Either it is not tool-capable "
              "through the gateway, or the tool payload was rejected. This is the "
              "failure the unit suite cannot see.")
        return 1

    parsed = json.loads(arguments) if arguments else {}
    print(f"    arguments parsed: {parsed}")
    if not parsed:
        print("WARN: the tool call arrived with EMPTY arguments. Under "
              "OpenAILLMService this call is DROPPED before any handler runs "
              "(pipecat openai/base_llm.py:464). See the plan's difference #1.")

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 4: Run the harness against the CURRENT Anthropic service, and record the before**

The harness calls `create_gateway_llm`, which does not exist yet. For this step only, run it with a two-line local shim so it exercises **today's** service:

```bash
docker compose up -d --build voice-agent
docker compose exec voice-agent python - <<'PY'
import asyncio, sys
sys.path.insert(0, "/app")
import src.pipeline.services as services
from src.config import get_settings
_s = get_settings()
services.create_gateway_llm = lambda model: services.create_anthropic_llm(
    api_key=_s.voice_anthropic_api_key, model=_s.voice_anthropic_model)
sys.argv = ["smoke"]
exec(open("/app/scripts/smoke_llm_service.py").read().replace('if __name__ == "__main__":', 'if False:'))
sys.exit(asyncio.run(main()))
PY
```

Note `scripts/` is **not** copied into the image (`Dockerfile:37` copies `src/` only) — mount it: `docker compose run --rm -v "$PWD/voice-agent/scripts:/app/scripts" voice-agent python /app/scripts/smoke_llm_service.py`, or `docker cp` it in. **Record the exact output**, especially `[5] saw_tool_call=` and `max_tokens=`. That line is the before-value phase 7 must reproduce. If the Anthropic key or the gateway is unavailable, **say so and record that the before-value could not be captured** — do not skip silently.

- [ ] **Step 5: Run the suite and commit**

```bash
cd voice-agent && PYTHONPATH=/Users/nitinbhat/PycharmProjects/OpenRecruiting/intake-core python3 -m pytest -q
```
Expected: **73 passed** (68 + 5, three of them `xfail`ed → pytest reports them separately; paste the exact line, e.g. `70 passed, 3 xfailed`).

```bash
git add voice-agent/tests/pipeline/test_llm_service.py voice-agent/scripts/smoke_llm_service.py
git diff --cached
git commit -m "test(voice-agent): pin the LLM service contract and build the real-pipecat harness before the swap"
```

Commit body: the measured baseline, the harness's before-output, and one sentence saying the unit tests cannot catch a pipecat incompatibility and why.

---

### Task 2: Swap the service — one commit, because the config rename breaks all five sites at once

`PipelineConfig`'s field rename touches every construction site simultaneously; splitting it leaves `main.py` passing kwargs a dataclass no longer has, which is a `TypeError` at pipeline construction — i.e. only when a recruiter connects. **One commit: services, factory, five main.py sites, config, requirements, the screening conftest, and the three stale docstrings.**

**Files:**
- Modify: `voice-agent/src/pipeline/services.py`, `src/pipeline/factory.py`, `src/main.py`, `src/config.py`, `requirements.txt`, `tests/screening/conftest.py`, `src/pipeline/tool_dispatch.py`, `src/pipeline/turn_persist.py`, `scripts/smoke_test_v2.py`, `tests/pipeline/test_llm_service.py`

**Interfaces:**
- Produces: `create_gateway_llm(*, model: str) -> OpenAILLMService`; `PipelineConfig.llm_base_url` / `.llm_api_key` / `.llm_model`.
- Removes: `create_anthropic_llm`, `PipelineConfig.anthropic_api_key`, `PipelineConfig.anthropic_model`, `Settings.voice_anthropic_api_key`, `Settings.anthropic_model_sonnet`.

- [ ] **Step 1: Rewrite `voice-agent/src/pipeline/services.py`**

Replace `:3`:
```python
from pipecat.services.anthropic.llm import AnthropicLLMService
```
with:
```python
from pipecat.services.openai.llm import OpenAILLMService
```

Replace `:39-44`:
```python
def create_anthropic_llm(api_key: str, model: str) -> AnthropicLLMService:
    return AnthropicLLMService(
        api_key=api_key,
        model=model,
        params=AnthropicLLMService.InputParams(enable_prompt_caching=True),
    )
```
with:
```python
# Anthropic's default max_tokens was 4096 (pipecat anthropic/llm.py:162) and was
# always sent. OpenAILLMService defaults BOTH max_tokens and
# max_completion_tokens to NOT_GIVEN (openai/base_llm.py:86-87), so neither
# leaves the process and LiteLLM's own default silently decides where this
# realtime path truncates. Truncation mid-tool-call is what produces the dropped
# update_answer described in src/pipeline/empty_turn.py, so this number is a
# guard, not a tuning knob. It restores exactly what shipped before phase 7.
_MAX_TOKENS = 4096


def create_gateway_llm(*, model: str) -> OpenAILLMService:
    """The pipecat LLM service, pointed at the LiteLLM gateway.

    `model` is a GATEWAY ALIAS, not a provider model id — litellm-config.yaml
    maps it. The gateway address and key come from llm_core's settings rather
    than voice-agent's own, deliberately: the coverage tracker in this same
    process already reaches the gateway through llm_core (main.py:2176), and two
    independent readings of LLM_GATEWAY_URL is how a pipeline ends up talking to
    one gateway while its tracker talks to another.

    Prompt caching does not survive this swap (the old service passed
    enable_prompt_caching=True). The spec accepts that loss explicitly; it is a
    cost and TTFT regression on long personas, not a correctness one.
    """
    from llm_core.settings import get_settings as get_llm_settings

    llm_settings = get_llm_settings()
    if not llm_settings.api_key:
        raise RuntimeError(
            "LITELLM_MASTER_KEY is not set. AsyncOpenAI would raise deep inside "
            "pipecat at the first WebRTC connection instead of here, so this "
            "fails at construction on purpose."
        )
    return OpenAILLMService(
        model=model,
        api_key=llm_settings.api_key,
        base_url=f"{llm_settings.gateway_url}/v1",
        params=OpenAILLMService.InputParams(max_tokens=_MAX_TOKENS),
    )
```

**Verify the `/v1` suffix against the running gateway before committing** — `llm_core`'s own client is the reference for how this repo addresses LiteLLM. Read `llm-core/llm_core/client.py`'s base-URL construction and match it exactly; if llm-core already appends `/v1`, `gateway_url` here must not append it twice. A wrong suffix produces a 404 at the first turn and a green `/health` forever.

- [ ] **Step 2: Rename the fields in `voice-agent/src/pipeline/factory.py`**

`:19` — `create_anthropic_llm` → `create_gateway_llm` in the import block.

`:33-34`:
```python
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5-20250929"
```
becomes:
```python
    # A GATEWAY ALIAS, not a provider model id — litellm-config.yaml maps it.
    # There is no api-key field: create_gateway_llm reads the gateway address and
    # master key from llm_core's settings, so a caller cannot accidentally hand
    # this pipeline a provider credential.
    llm_model: str = "voice-intake"
```

`:81-84`:
```python
        llm = create_anthropic_llm(
            api_key=config.anthropic_api_key,
            model=config.anthropic_model,
        )
```
becomes:
```python
        llm = create_gateway_llm(model=config.llm_model)
```

**Note on Task 1's test:** it asserts `llm_base_url` and `llm_api_key` are present in `factory.py`. Reading them from `llm_core` instead is the better design (one source of truth for the gateway) — so **update that assertion in Task 1's file to match**, and say why in the commit. Do not add fields to `PipelineConfig` just to satisfy a test written a task earlier; fix the test, and record that the test was wrong, not the code.

- [ ] **Step 3: The five `main.py` sites**

At `:491-492`, `:708-709`, `:1232-1233`, `:1848-1849`, `:2183-2184`, replace each pair:
```python
        anthropic_api_key=settings.voice_anthropic_api_key,
        anthropic_model=settings.voice_anthropic_model,
```
with a single line — `llm_model=settings.voice_llm_model,` for now. **Task 4 splits it into three settings**; keeping one knob here makes Task 2 a pure swap and keeps the two changes independently revertible.

`:426`:
```python
    logger.info(f"Anthropic model: {settings.voice_anthropic_model}")
```
becomes:
```python
    logger.info(f"LLM gateway alias: {settings.voice_llm_model}")
```

- [ ] **Step 4: `voice-agent/src/config.py`**

Delete `:20` (`voice_anthropic_api_key`) — **this is the last provider credential in this codebase.** Delete `:45` (`anthropic_model_sonnet`), which has had **zero readers** since phase 3 moved the coverage tracker; verify with `grep -rn "anthropic_model_sonnet" voice-agent/` before deleting. Replace `:21`:

```python
    voice_anthropic_model: str = "claude-sonnet-4-5-20250929"
```
with:
```python
    # A GATEWAY ALIAS, not a provider model id — litellm-config.yaml maps it.
    # Reads VOICE_LLM_MODEL from the environment (pydantic-settings, case
    # insensitive). Split into three per-workload settings in Task 4.
    voice_llm_model: str = "voice-intake"
```

- [ ] **Step 5: `voice-agent/requirements.txt:1`**

```
pipecat-ai[anthropic,deepgram,webrtc]==0.0.102
```
becomes:
```
# No [anthropic] extra: it is the only thing that installs the Anthropic SDK
# (METADATA: `anthropic~=0.49.0; extra == "anthropic"`), and phase 7 removed the
# last import of it. No [openai] extra is needed either — `openai` is a CORE
# pipecat dependency (`Requires-Dist: openai<3,>=1.74.0`, no marker); the extra
# only adds websockets support for the Realtime service, which we do not use.
pipecat-ai[deepgram,webrtc]==0.0.102
```

- [ ] **Step 6: `voice-agent/tests/screening/conftest.py`**

`:46-47`:
```python
    "pipecat.services.anthropic",
    "pipecat.services.anthropic.llm",
```
becomes:
```python
    "pipecat.services.openai",
    "pipecat.services.openai.llm",
```
and delete `:16` (`"anthropic",`). Update the module docstring at `:1-9` to stop naming anthropic.

**This is load-bearing.** `src.main` imports `src.pipeline.factory` → `src.pipeline.services` → `pipecat.services.openai.llm` at import time. Miss this and `tests/screening/` fails at collection with `ModuleNotFoundError`, on a host with no pipecat.

- [ ] **Step 7: The stale docstrings and the stale usage note**

- `src/pipeline/tool_dispatch.py:1` — "Map Anthropic tool calls to intake_core handlers." → "Map pipecat tool calls to intake_core handlers." (The dispatcher is shape-neutral; only the sentence is wrong.)
- `src/pipeline/turn_persist.py:97-100` — the comment says Anthropic tool turns use content blocks. `_text_of` handles `str` and list-of-parts and stays correct either way; rewrite the comment to say the universal context stores tool turns as `{"role":"assistant","tool_calls":[…]}` + `{"role":"tool",…}`, neither of which carries spoken text. **Do not change `_text_of`.**
- `scripts/smoke_test_v2.py:11` — `export ANTHROPIC_API_KEY=...` → `export LLM_GATEWAY_URL=http://localhost:4000` and `export LITELLM_MASTER_KEY=...`. That script has run through the gateway since phase 3; the docstring never caught up.
- `Dockerfile:31-33` — the comment ends "The pipecat LLM service is still Anthropic-bound — that is phase 7." Rewrite: phase 7 is done.

- [ ] **Step 8: Remove the xfail markers from Task 1's tests and run the suite**

```bash
cd voice-agent && PYTHONPATH=/Users/nitinbhat/PycharmProjects/OpenRecruiting/intake-core python3 -m pytest -q
```
Expected: **73 passed, 0 xfailed**. If a `strict=True` xfail is still marked it fails the run — that is the marker doing its job.

- [ ] **Step 9: Rebuild and verify against real pipecat — the step that actually proves the swap**

```bash
docker compose up -d --build voice-agent
docker compose exec voice-agent python -c "import anthropic" ; echo "exit=$?"
docker compose exec voice-agent python -c "import openai; print(openai.__version__)"
docker compose run --rm -v "$PWD/voice-agent/scripts:/app/scripts" voice-agent python /app/scripts/smoke_llm_service.py
make verify
```

Expected: `import anthropic` fails with `ModuleNotFoundError` and a **non-zero** exit; `openai` still reports **2.52.0** (if pip resolved it down, `llm-core`'s `openai<3.0` pin has been re-narrowed — CHECKPOINT blocker B1, do not fix by re-narrowing); the harness prints `saw_tool_call=True` with parseable arguments and `max_tokens=4096`; `make verify` shows `ok voice-agent`.

**`make verify` is a smoke check.** The harness is the verification. If the harness cannot run (no gateway, no key), **say so in the commit body in those words** and do not claim the swap was verified.

- [ ] **Step 10: Self-review and commit**

```bash
git add voice-agent/src voice-agent/requirements.txt voice-agent/tests voice-agent/scripts voice-agent/Dockerfile
git diff --cached
git commit -m "feat(voice-agent)!: run the pipecat pipeline through the LiteLLM gateway and delete the last provider credential"
```

Self-review checklist for this diff specifically:
- [ ] `grep -rn "anthropic" voice-agent/src voice-agent/requirements.txt` returns **nothing**.
- [ ] `grep -rn "voice_anthropic" .` returns nothing outside `backend/app/config.py` (Task 5's) and `docs/`.
- [ ] All five `main.py` sites changed — count them: `grep -c "llm_model=settings" voice-agent/src/main.py` must be **5**.
- [ ] `PipelineConfig` has no api-key field at all.
- [ ] `tests/screening/conftest.py` stubs `pipecat.services.openai.llm`.
- [ ] The commit body carries: the voice count, the `import anthropic` exit code, the harness output, and whether a live WebRTC session was run.

---

### Task 3: Make the dropped tool call and the silent turn audible

Difference #1 is a **regression this phase introduces**: under `AnthropicLLMService` a tool call with empty arguments is dispatched with `{}` and comes back `{"ok": False, "error": "unknown qid: None"}`; under `OpenAILLMService` it is dropped at `openai/base_llm.py:464` before any of our code runs. We cannot fix pipecat's branch without vendoring its internals — a fork that would rot on the next bump. We can refuse to let it be silent.

`FunctionCallsStartedFrame` is broadcast **only** when at least one call survived (`llm_service.py:625-631`), and `LLMFullResponseEndFrame` is pushed from the `finally` (`base_llm.py:526-528`), so "an LLM turn produced neither text nor a surviving tool call" is exactly detectable from frames we already see. That also catches the pre-existing case where the model returns nothing at all and the bot simply goes quiet.

**Files:**
- Create: `voice-agent/src/pipeline/empty_turn.py`, `voice-agent/tests/pipeline/test_empty_turn.py`
- Modify: `voice-agent/src/pipeline/factory.py`, `voice-agent/tests/pipeline/conftest.py`

- [ ] **Step 1: Write the failing test**

Create `voice-agent/tests/pipeline/test_empty_turn.py` with four tests, driving `EmptyTurnDetector` through the stubbed frame classes:

1. `test_a_turn_with_text_is_not_flagged` — Start → `LLMTextFrame("hi")` → End ⇒ no warning.
2. `test_a_turn_with_a_surviving_tool_call_is_not_flagged` — Start → `FunctionCallsStartedFrame` → End ⇒ no warning.
3. `test_a_turn_with_neither_is_flagged_by_name` — Start → End ⇒ exactly one `llm_empty_turn` record, carrying the turn index and the configured alias.
4. `test_every_frame_is_forwarded_unchanged` — the detector is observational; assert each input frame reaches `push_frame` in order. **A guard that swallows frames would break TTS**, which is why this test exists.

Add `LLMTextFrame` and `FunctionCallsStartedFrame` to `voice-agent/tests/pipeline/conftest.py`'s `_frames_mod` (`:61-68`) as real stub classes, beside the existing `LLMFullResponseStartFrame` / `LLMFullResponseEndFrame`.

- [ ] **Step 2: Run to verify it fails**

```bash
cd voice-agent && PYTHONPATH=/Users/nitinbhat/PycharmProjects/OpenRecruiting/intake-core python3 -m pytest -q tests/pipeline/test_empty_turn.py
```
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pipeline.empty_turn'`.

- [ ] **Step 3: Write the detector**

`voice-agent/src/pipeline/empty_turn.py` — a `FrameProcessor` that resets on `LLMFullResponseStartFrame`, records `LLMTextFrame` and `FunctionCallsStartedFrame`, and on `LLMFullResponseEndFrame` logs `logger.warning("llm_empty_turn", …)` when it saw neither. Its docstring must carry the *reason*:

```
An LLM turn that produced no speech and no tool call is invisible from every
other vantage point in this service. /health stays green; the transcript simply
has no row; the recruiter hears silence and assumes they were not understood.

Two distinct causes land here, and both matter:

* the model returned nothing;
* a tool call was DROPPED. OpenAILLMService only appends the final tool call if
  its accumulated argument string is truthy (pipecat openai/base_llm.py:464), so
  a truncated update_answer disappears before run_function_calls is reached — no
  handler, no result callback, no FunctionCallsStartedFrame, no error. The
  service this replaced coerced the same case to `{}` and dispatched it
  (anthropic/llm.py:474), which surfaced as {"ok": false} the model could see.
  That difference is why this processor exists.

This does not repair either case. It converts them from silence into one named
log line that a session review can grep for. Repairing the dropped call means
overriding pipecat's _process_context, which is a fork of ~100 lines of its
internals and is deliberately not done here.
```

- [ ] **Step 4: Wire it into the pipeline**

In `factory.py`, construct the detector and place it **immediately after `llm`** in the `Pipeline([...])` list at `:227-245` — after the service that emits the frames, before `md_stripper`. Pass the alias for the log line.

- [ ] **Step 5: Run the suite**

```bash
cd voice-agent && PYTHONPATH=/Users/nitinbhat/PycharmProjects/OpenRecruiting/intake-core python3 -m pytest -q
```
Expected: **77 passed**.

- [ ] **Step 6: Rebuild and commit**

```bash
docker compose up -d --build voice-agent && make verify
git add voice-agent/src/pipeline/empty_turn.py voice-agent/src/pipeline/factory.py voice-agent/tests/pipeline
git diff --cached
git commit -m "fix(voice-agent): name the turn that produced neither speech nor a tool call"
```

---

### Task 4: One alias per workload

Five pipelines share one model setting today, so voice screening cannot be pointed at a local model without moving voice intake too — and independent repointing is the deliverable of this whole effort. This is the same split phases 2 and 4 made. **All three aliases resolve to the same model, so this task changes no behaviour.**

- [ ] **Step 1: Add the two aliases and document the third**

In `litellm-config.yaml`, above `:121` (`voice-intake`) add the tier comment B12 has been asking for since recon — that the voice path ran `claude-sonnet-4-5-20250929` (`voice-agent/src/config.py:21`, never overridden in `.env`) and this alias deliberately carries the same phase-1 sonnet-4-6→sonnet-5 bump every other alias took. Then add two siblings, both `anthropic/claude-sonnet-5`, both `supports_function_calling: true`:

- `voice-screening` — with a comment noting it is the only voice pipeline besides intake that sends tools (`main.py:1859`, `ALL_SCREENING_TOOLS`), so an alias without native function calling disables the screening agent rather than degrading it. Same warning `INTAKE_TEXT_MODEL` carries at `backend/app/config.py:189-195`.
- `voice-feedback` — feedback v1 and v2 (RTVI), no tools.

- [ ] **Step 2: Reload the gateway and verify all three live**

```bash
docker compose restart litellm
curl -s -H "Authorization: Bearer $LITELLM_MASTER_KEY" http://localhost:4000/model/info | python3 -c "import sys,json; print(sorted(m['model_name'] for m in json.load(sys.stdin)['data']))"
```
Expected: 27 aliases, including all three `voice-*`. Then one real completion per **new** alias, confirming each answers — the same live check `502cd84` used. Paste the results.

- [ ] **Step 3: Split the setting**

`voice-agent/src/config.py` — `voice_llm_model` becomes three fields:
```python
    voice_intake_model: str = "voice-intake"
    voice_screening_model: str = "voice-screening"
    voice_feedback_model: str = "voice-feedback"
```

`main.py`: `:492` and `:1233` → `voice_feedback_model`; `:709` and `:2184` → `voice_intake_model`; `:1849` → `voice_screening_model`. `:426` logs whichever one that handler uses.

- [ ] **Step 4: Add the test, run, rebuild, commit**

Add one test to `tests/pipeline/test_llm_service.py` asserting `main.py` names three distinct settings and that no site still reads a single shared model knob — the property that makes the aliases repointable, and the one a future "simplification" would quietly undo.

```bash
cd voice-agent && PYTHONPATH=/Users/nitinbhat/PycharmProjects/OpenRecruiting/intake-core python3 -m pytest -q   # 78 passed
docker compose up -d --build voice-agent && make verify
docker compose run --rm -v "$PWD/voice-agent/scripts:/app/scripts" voice-agent python /app/scripts/smoke_llm_service.py
git add litellm-config.yaml voice-agent/src voice-agent/tests
git diff --cached
git commit -m "feat(voice-agent): give intake, screening and feedback their own gateway aliases"
```

---

### Task 5: Close the last provider egress in the repo — decision gate first

**The brief's DoD ("nothing holds a provider API key except the litellm proxy") is NOT satisfied by phase 7's voice scope.** Verified by repo-wide grep at HEAD, two backend modules still POST raw `httpx` to `https://api.anthropic.com/v1/messages` with `x-api-key: settings.ANTHROPIC_API_KEY`:

| site | call | model setting | degraded reply today |
|---|---|---|---|
| `backend/app/services/candidate_detection_service.py:118` (`_ANTHROPIC_URL`), `:139-155` | tier-3 candidate detection, `max_tokens=256`, reads `resp_json["content"][0]["text"]` | `CANDIDATE_DETECT_MODEL` = `claude-3-5-haiku-latest` (`config.py:124`) | returns `None`; callers treat it as "no detection" — **safe** |
| `backend/app/services/recall_webhook/end_state.py:34`, `:215-236` | `_llm_judge`, end-of-interview phase, `max_tokens=256`, same envelope | `END_STATE_MODEL` = `claude-sonnet-4-6` (`config.py:128`) | returns `None`; callers fall through — **safe** |

These were **deliberately excluded** and the exclusion is written down: `backend/tests/test_no_provider_sdk.py:13-17` says they "belong to no phase in the current rollout … see the spec's six-surface inventory, which does not list them." That was correct while phases remained. Phase 7 is the last one, so the exclusion now *is* the gap.

**Both aliases already exist and were created for exactly these call sites**, in phase 1, and have never been read: `candidate-detect` (`litellm-config.yaml:100-104`, haiku, with a comment naming `Settings.CANDIDATE_DETECT_MODEL`) and `end-state` (`:115-119`, sonnet). Whoever wrote the config expected this task to happen.

- [ ] **Step 1: The decision gate — record the answer before writing code**

This is the only task in the plan that touches `backend/`, i.e. the only one that can move the 2186/5 gate in the final phase. Choose and write the choice into the commit body:

- **Migrate (recommended).** Both are single non-streaming, non-tool JSON-in-prose calls — the same shape phase 4b migrated in two files. The aliases exist. Doing it makes the DoD literally true.
- **Defer.** Then the DoD below is amended to name these two sites explicitly as the known remainder, `test_no_provider_sdk.py`'s exclusion comment is updated to say "deferred past phase 7" rather than "belongs to no phase", and CHECKPOINT records an open item. **What is not acceptable is a DoD that claims no provider key remains while these two exist.**

- [ ] **Step 2: Migrate both call sites**

Each becomes `llm_core`'s `complete()`, following `backend/app/services/intake/` precedent: `from llm_core import llm` (module-level `__getattr__`, no import-time client construction — `llm-core/llm_core/__init__.py:18-29`), `await llm.complete(model=settings.CANDIDATE_DETECT_MODEL, max_tokens=256, temperature=0, messages=[…])`, read `reply.text`. Delete `_ANTHROPIC_URL`, the `x-api-key`/`anthropic-version` headers, and the `resp_json["content"][0]["text"]` read from both.

`config.py`: `CANDIDATE_DETECT_MODEL` → `"candidate-detect"`, `END_STATE_MODEL` → `"end-state"`, each with the "A GATEWAY ALIAS, not a provider model id" comment this file already uses at `:182, 189, 202`. Delete `ANTHROPIC_API_KEY` (`:113`) and `VOICE_ANTHROPIC_API_KEY` / `VOICE_ANTHROPIC_MODEL` (`:175-176`) — **all three now have zero readers in `backend/app`; verify by grep before deleting.**

**Keep the `None`-on-failure behaviour in both.** It is the safe default here (no detection / no phase verdict), unlike the six dangerous ones this effort has fixed. Do not "improve" it into a raise in the same commit as a migration.

- [ ] **Step 3: Rewrite the two test files**

`backend/tests/services/test_cal_intel_detection.py` — `:167` (`s.ANTHROPIC_API_KEY`), `:247-268` and `:270-278` patch `d.httpx.AsyncClient`. Convert to the `fake_llm` fixture (llm-core's pytest11 entry point; already used by 8+ backend test files, e.g. `backend/tests/services/test_jd_extract_service.py`). `backend/tests/services/test_end_state.py` — `:139-218`, same treatment; `_fake_http_client` and the `content[0].text` envelope go away, the `_llm_judge`-level tests at `:28-121` are untouched because they patch `_llm_judge` itself.

**Replace 1-for-1**; the failure-path tests (bad shape, HTTP error, exception) map onto `fake_llm`'s error injection. Add two guards: each site's model kwarg is the alias, not a provider model id.

- [ ] **Step 4: Extend the repo-wide guard**

In `backend/tests/test_no_provider_sdk.py`, retire the `:13-17` exclusion paragraph and add:

```python
def test_no_application_module_holds_a_provider_credential():
    """The phase-7 deliverable, repo-wide. Only litellm-config.yaml may name a
    provider key; every application reaches a provider through the gateway.

    Scanned as source text over every service's source tree, because the failure
    mode is someone reintroducing a direct client — which no import check in a
    single service's suite would ever see."""
    ...  # walk backend/app, voice-agent/src, intake-core/intake_core,
         # llm-core/llm_core, workers/*/src for "api.anthropic.com",
         # "ANTHROPIC_API_KEY", "x-api-key", "from anthropic import"
         # → assert the set is empty. Skip (not fail) when the repo root is not
         # reachable, mirroring test_intake_core_does_not_pin_the_sdk_transitively.
```

Note `make test` mounts only `backend/`, so the repo-root reachability skip is required — copy the pattern from `test_intake_core_does_not_pin_the_sdk_transitively` at `:52-60`.

- [ ] **Step 5: Run everything**

```bash
make test                                                     # ≥ 2188 passed, 5 skipped
cd llm-core && python3 -m pytest -q                            # 199 passed, 12 deselected
cd intake-core && python3 -m pytest -q                         # 83 passed
docker compose up -d --build backend && make verify
```

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests
git diff --cached
git commit -m "feat(backend): move candidate detection and end-state onto the gateway, closing the last provider egress"
```

---

### Task 6: The voice build paths, the final sweep, and CHECKPOINT

- [ ] **Step 1: `voice-agent/build-with-intake-core.sh` — the B5 analogue nobody filed**

This EC2 path stages `intake-core-pkg/` (`:19-24`) and delegates to `deploy-config/backend-deploy/docker-compose.yml` (`:27-30`). It **does not stage `llm-core`** — so it has been unable to produce a working image **since phase 3** made the coverage tracker import `llm_core`, three phases before this one. `deploy-config/` is not in this checkout (verified: no such directory), so the Dockerfile it feeds cannot be read or built here.

Apply CHECKPOINT's settled B5 rule: **fix the path, never delete a deploy path you cannot prove is dead.** Add an `llm-core-pkg` staging block mirroring `:19-24`, and a header comment stating plainly that the compose Dockerfile in this repo copies `intake-core`/`llm-core` from the repo root instead, that this script targets a compose file outside this checkout, and that it could not be executed here. Do not guess at the deploy-config Dockerfile's contents.

- [ ] **Step 2: The final sweep — run every command in the Definition of Done and paste the output.**

- [ ] **Step 3: Update `.superpowers/sdd/CHECKPOINT.md`**

Phase 7 DONE and the effort complete. Record: the new voice baseline; the backend number after Task 5; that recon's three B16 claims were verified TRUE with the two caveats it missed; the corrected `PipelineConfig` site list (`:2181`, not `:2178`); the two `OpenAILLMService`-vs-`AnthropicLLMService` behaviour differences with their pipecat line numbers, because they are properties of pipecat 0.0.102 and will need re-checking on any bump; whether a live WebRTC session was run; and B12/B14/B15's final state.

- [ ] **Step 4: Commit**

```bash
git add voice-agent/build-with-intake-core.sh .superpowers/sdd/CHECKPOINT.md
git diff --cached
git commit -m "chore(voice-agent): stage llm-core in the EC2 build path and close out the gateway migration"
```

---

## Definition of done for this plan

- `grep -rn "anthropic" voice-agent/src voice-agent/requirements.txt` returns **nothing**; `voice-agent/src/pipeline/services.py` imports `pipecat.services.openai.llm`.
- `docker compose exec voice-agent python -c "import anthropic"` fails with `ModuleNotFoundError` and a non-zero exit; `docker compose exec voice-agent python -c "import openai; print(openai.__version__)"` still prints **2.52.0** (a downgrade means llm-core's `openai<3.0` pin was re-narrowed — blocker B1, do not "fix" it that way).
- `grep -rn "voice_anthropic_api_key\|VOICE_ANTHROPIC_API_KEY" .` returns nothing outside `docs/` and `.superpowers/`. **`settings.voice_anthropic_api_key` was the last provider credential read by any application in this repo.**
- **The repo-wide credential check**, run from the repo root and pasted into the final commit:
  ```bash
  grep -rn "api\.anthropic\.com\|ANTHROPIC_API_KEY\|x-api-key\|from anthropic import" \
    backend/app voice-agent/src intake-core/intake_core llm-core/llm_core workers/*/src \
    --include="*.py" ; echo "exit=$? (1 == clean)"
  ```
  Must return **nothing**. `litellm-config.yaml` (21 `os.environ/ANTHROPIC_API_KEY` entries) and `.env` are the only legitimate holders, because the proxy is the egress point. Pinned by `test_no_application_module_holds_a_provider_credential`. **If Task 5's decision gate deferred the two backend sites, this bullet is amended to name them and CHECKPOINT records an open item — it is not quietly dropped.**
- All five `PipelineConfig(...)` sites pass a gateway alias and no key: `grep -c "llm_model=settings\|_model=settings.voice_" voice-agent/src/main.py` == **5**, and three distinct settings are in use.
- `voice-agent` green at **78 passed** (68 baseline + 5 + 4 + 1), counts pasted in every commit that touches it, **and every run used `PYTHONPATH=…/intake-core`** — the invocation is part of the result.
- Backend `make test` green at **2186 passed, 5 skipped** after Tasks 1-4 and 6 (unchanged), and **≥ 2188 / 5** after Task 5. `intake-core` **83**, `llm-core` **199 passed / 12 deselected**, `intake-agent` **17** — all unchanged, all re-run at the end.
- `docker compose up -d --build voice-agent && make verify` shows all services `ok`, including `ok voice-agent`. **Recorded as a smoke check, not as verification of the swap** — `create_pipeline` runs only on a WebRTC connection.
- `voice-agent/scripts/smoke_llm_service.py` runs green inside the container: the real `OpenAILLMService`, the real adapter, non-empty `properties`/`required` on every tool reaching pipecat, `max_tokens=4096`, and one live streaming call that returns a `tool_calls` delta with parseable arguments. Its Task-1 before-run against `AnthropicLLMService` and its Task-2 after-run are both pasted.
- **A live WebRTC voice session was run, or the commit says explicitly that it was not and why.** No substitute is accepted: `make verify` proves `/health`, and `smoke_test_v2.py` never constructs a pipecat service.
- Every behaviour difference has a stated answer: `max_tokens` restored to 4096 in `services.py`; prompt caching accepted as lost (spec §Risks); the dropped-tool-call and no-reply cases produce a named `llm_empty_turn` warning, with `empty_turn.py`'s docstring recording that this makes them audible rather than repaired, and why forking pipecat's `_process_context` was rejected.
- Three aliases (`voice-intake`, `voice-screening`, `voice-feedback`), all sonnet, all live-verified via `/model/info` plus one real completion each; `voice-intake`'s tier finally documented in `litellm-config.yaml` (B12).
- `voice-agent/build-with-intake-core.sh` stages `llm-core`, or the commit records why it could not be verified.
- `.superpowers/sdd/CHECKPOINT.md` updated: phase 7 DONE, the effort complete, the corrections below folded in.

## What recon and the spec got wrong — verified against source at HEAD

1. **The spec's `voice-agent` row is half-done already.** Line 207 names `pipeline/services.py:39` **and** `main.py:2172`. The second migrated in phase 3 with the coverage tracker; `main.py:2176-2179` now builds an `llm_core` client on alias `voice-intake`. Planning it again would have produced a no-op task and a confusing diff.
2. **Recon B11's line numbers have drifted.** It lists `PipelineConfig(` at `489, 706, 1230, 1846, 2178`. The last is now **2181** — phase 3 inserted the `llm_core` import block above it. The `anthropic_api_key=` kwargs are at `491, 708, 1232, 1848, 2183`.
3. **Recon B16 called the `[anthropic]` extra "harmless" to keep.** It is not: `Requires-Dist: anthropic~=0.49.0; extra == "anthropic"` is the *only* thing installing the SDK into the voice image, and `anthropic 0.49.0` is installed there today. Keeping it leaves a provider SDK in the last service that was supposed to lose one, and defeats the `import anthropic` check.
4. **Recon B16 says the swap has no framework blocker and is right — but it never looked at the two services' degraded-reply branches, which is where the only real regression lives.** `anthropic/llm.py:474` dispatches a tool call with `{}` when arguments are empty; `openai/base_llm.py:464` drops it entirely. Recon's "OpenAILLMService CAN replicate the context aggregation, tool format and streaming" is true and also not the question.
5. **Neither recon nor the spec noticed `max_tokens`.** `AnthropicLLMService.InputParams` defaults it to 4096 (`anthropic/llm.py:162`) and always sends it; `BaseOpenAILLMService` defaults it to `NOT_GIVEN` (`openai/base_llm.py:86`) and sends nothing. A literal swap silently hands the realtime path's truncation point to LiteLLM's default.
6. **The DoD the brief asks for cannot be met by the voice scope, and the exclusion is already written down in the repo.** `backend/app/services/candidate_detection_service.py:118,142` and `backend/app/services/recall_webhook/end_state.py:34,223` still POST to `api.anthropic.com` with `settings.ANTHROPIC_API_KEY`; `backend/tests/test_no_provider_sdk.py:13-17` documents them as deliberately out of the rollout. Their aliases (`candidate-detect`, `end-state`) have existed since phase 1 and have never been read. Task 5.
7. **Three settings are already dead and would have been carried forward unnoticed:** `voice-agent/src/config.py:45` `anthropic_model_sonnet` (zero readers since phase 3), `backend/app/config.py:175-176` `VOICE_ANTHROPIC_API_KEY` / `VOICE_ANTHROPIC_MODEL` (zero readers in `backend/app`).
8. **Recon B15 is partly closed.** `voice-agent` now **does** `depends_on: [litellm]` (`docker-compose.yml`), added when the coverage tracker moved. The other three workers still do not.
9. **Recon's voice-agent test inventory is stale** — 11 test files now, 68 tests, including `tests/pipeline/test_tool_schemas.py` which phase 4 Task 1 added. `tests/pipeline/test_tool_dispatch.py:1`'s "Anthropic" reference is a docstring; the test itself is shape-neutral.

## Carried forward

- **B14: `.env` still has no `LLM_GATEWAY_URL`.** Harmless in compose — both `llm_core` and (after Task 2) the pipecat service fall back to `http://litellm:4000`, which is correct inside the network — and wrong for any host-side run. `.env.example:129` has it. Every host-side command in this plan that reaches a gateway exports it.
- **B15 for the three workers:** `feedback-agent`, `intake-agent`, `intake-context-builder` still lack `depends_on: litellm`. One line each; not phase 7's, and not reachable in practice because all three are invoked on demand rather than at boot.
- **Prompt caching is gone from the voice path** and there is no OpenAI-side equivalent through LiteLLM today. Accepted by the spec, but it is a live cost/TTFT regression on long personas and should be measured once real sessions run.
- **`voice-agent` still has no end-to-end test of `build_pipeline`.** Phase 4 tested the tool-schema reader; this phase tests the service contract and adds the harness. The factory's processor ordering, the RTVI path and the summarization path remain covered only by a live call.
- **`deploy-config/` is absent from this checkout**, so `voice-agent/src/config.py:8`'s `env_file` path resolves to nothing and every setting comes from the process environment. That is correct under compose and worth knowing before anyone debugs a "setting not picked up" report.
- **These behaviour differences are properties of pipecat 0.0.102**, cited by file and line. **Re-check them on any pipecat bump** — particularly `openai/base_llm.py:464`, which is one truthiness test away from changing character.
