# `intake-core` + `intake-context-builder` LLM Migration Implementation Plan (Phase 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the OpenAI tool shape the *only* shape `intake-core` exports — deleting `_as_openai_tool`, `ALL_TOOLS` and `screening/tools.py`'s `input_schema` — and move `workers/intake-context-builder` off the Anthropic SDK entirely, so that after this phase `grep -rn "input_schema" intake-core/intake_core workers/` returns nothing, `workers/intake-context-builder/src/clients/anthropic.py` does not exist, and no file in either package imports `anthropic`.

**Architecture:** Phase 3 left `intake-core` deliberately dual-shaped: `ALL_TOOLS` (Anthropic) is canonical and `ALL_TOOLS_OPENAI` is *derived from it by reference* (`parameters is input_schema`). That was correct then, because `voice-agent` hands `ALL_TOOLS` to pipecat and **no voice test covers the code that reads it**. This phase inverts the derivation and deletes the Anthropic side. Doing so breaks `voice-agent/src/pipeline/factory.py` in the same breath (blocker B2), so this plan first *builds the missing test* around that reader (Task 1) and then flips everything it reads in one atomic commit (Task 2). Phase 4b then moves `intake-context-builder`'s two pure JSON-in-prose calls onto `llm.complete` — the easiest migration in the effort in code terms, and the one carrying the effort's single most dangerous default (`_empty_answers()` presented to a recruiter as a successful prefill).

**Tech Stack:** Python 3.11, `llm-core` (`openai` async client → LiteLLM proxy), `intake-core`, pipecat 0.0.102 (voice), FastAPI, pytest + pytest-asyncio (explicit `@pytest.mark.asyncio` outside the backend), Docker Compose.

**Source spec:** `docs/superpowers/specs/2026-08-07-provider-agnostic-llm-design.md` (§Per-service migration rows for `intake-core` and `workers/intake-context-builder`)
**Prior phase:** `docs/superpowers/plans/2026-08-10-phase3-backend-streaming.md` (COMPLETE)
**Live state:** `.superpowers/sdd/CHECKPOINT.md` — **BINDING, and it supersedes the spec wherever they disagree.**
**Recon:** `.superpowers/sdd/phases-4-7-recon.md` — every claim this plan relies on was re-verified against source at HEAD `5eaaaa5`. Corrections are listed in "What recon and the spec got wrong" below.

---

## SCOPE — what phase 4 is NOT

- **The coverage tracker is ALREADY MIGRATED.** Phase 3 Task 4 moved it. `intake-core/intake_core/coverage_tracker.py:42-49` now takes `llm` (not `anthropic_client`) and calls `llm.complete` at `:91`. Verified at HEAD. **Do not re-plan it, do not rename it, do not touch `intake-core/tests/test_coverage_tracker.py`.**
- **`intake-core` no longer pins `anthropic`.** `intake-core/pyproject.toml:6-10` lists exactly `pydantic`, `supabase`, `structlog`. Phase 3 removed the pin. Blocker B4 is CLOSED; the spec's "drop the `anthropic` dependency" row for `intake-core` is already done.
- **`voice-agent`'s pipecat LLM service stays Anthropic.** `create_anthropic_llm` (`voice-agent/src/pipeline/services.py:39`) and all five `PipelineConfig(...)` sites are phase 7. This phase touches `factory.py`'s **tool-schema reader only**.
- **No prompt text changes.** A spec non-goal. `PARSE_JD_SYSTEM_PROMPT` and `SYNTHESIZE_SYSTEM_PROMPT` are copied, not edited.

---

## Blocker B2 — verified real, and it is worse than CHECKPOINT records

CHECKPOINT names `voice-agent/src/pipeline/factory.py:93-98`. Re-verified at HEAD, and there are **three** `t["name"]` readers of intake-core's tool dicts, not one:

| # | file:line | code | failure on the OpenAI shape |
|---|---|---|---|
| 1 | `voice-agent/src/pipeline/factory.py:95` | `name=t["name"],` | **KeyError** — pipeline construction crashes |
| 2 | `voice-agent/src/pipeline/factory.py:97-98` | `t.get("input_schema", {}).get("properties"/"required", …)` | silently `{}` / `[]` — but never reached, because #1 raises first |
| 3 | `voice-agent/src/pipeline/factory.py:232` | `tool_name = tool["name"]` | **KeyError** — a second, independent site inside the same `build_pipeline`, in the `register_function` loop. **CHECKPOINT does not name this one.** |
| 4 | `voice-agent/scripts/smoke_test_v2.py:56-57` | `{t['name'] for t in ALL_TOOLS}` | **KeyError** — the live smoke test phase 3 relied on for voice verification |

**And the coupling is wider than "intake tools".** `factory.py` reads `config.tools` generically. `voice-agent/src/main.py:2195` passes `ALL_TOOLS`; `voice-agent/src/main.py:1859` passes `ALL_SCREENING_TOOLS` (from `intake_core/screening/tools.py`) **through the same function**. So flipping `tools/schemas.py` without flipping `screening/tools.py` moves the KeyError from the intake pipeline to the screening pipeline. **`tools/schemas.py`, `screening/tools.py` and `factory.py` are one atomic unit.** That is Task 2.

**Do NOT do the half-move.** Keeping a top-level `"name"` while renaming `input_schema` turns a loud KeyError into `FunctionSchema(properties={}, required=[])` — a model handed two parameterless tools, an intake agent that silently stops recording answers, and no error anywhere. That is CHECKPOINT fact #3's bug shape with a three-phase fuse. Recon described this as the *expected* outcome; it is the outcome we are specifically avoiding.

**Do NOT make `factory.py` accept both shapes.** A tolerant reader is the same trap wearing a different hat: the day someone reintroduces an Anthropic dict it will be accepted and silently produce empty properties. Task 2's reader accepts exactly one shape and raises a named error on anything else.

---

## Blocker B5 — verified real, with the exact lines

| claim | verdict |
|---|---|
| `workers/intake-context-builder/deploy/ecr-push.sh:26` is `cd "$(dirname "$0")/.."` | **TRUE** |
| `…/deploy/ecr-push.sh:61` is `docker build --platform linux/amd64 -t "${REPO_NAME}:latest" -f production/Dockerfile .` | **TRUE** — build context is `workers/intake-context-builder/`, so `llm-core` at the repo root is **not visible** |
| `…/production/Dockerfile` has no `COPY llm-core` | **TRUE** — 13 lines total, no llm-core anywhere |
| `…/production/Dockerfile:11` is `COPY intake-core-pkg/ ${LAMBDA_TASK_ROOT}/intake_core/` and that directory does not exist | **TRUE**, and `workers/intake-context-builder/.gitignore:5` is literally `intake-core-pkg/`. **The Lambda deploy path is already broken or depends on an undocumented manual staging step — this predates the migration.** |

So B5 is real, and 4b's *code* is not blocked by it; only the Lambda deploy path is. The live path today is compose (`docker-compose.yml:200-212`, `env_file: [.env]`, reached via `JOB_INVOKER` + `CONTEXT_BUILDER_WORKER_URL` in `.env`) and its `Dockerfile` **already installs llm-core** (`workers/intake-context-builder/Dockerfile:19-20`, pre-baked by phase 2). Task 6 settles the deploy path.

---

## The degraded-reply question, per migrated call site

CHECKPOINT fact #3: *a degraded LLM reply lands on a default that reads as a REAL answer.* Five instances so far. Every site this phase touches, traced to its end:

| # | site | what a degraded/empty reply produces **today** | verdict | task |
|---|---|---|---|---|
| 1 | `intake_core/tools/schemas.py` consumers — `backend/app/services/intake/text_runner.py:38-48` builds `_REQUIRED_ARGS` from `spec["function"]["parameters"]["required"]` | a truncated call arrives as `input={}`, `_missing_args` catches it at `text_runner.py:343`, the call is refused and named back to the model | **already guarded (phase 3)** — but the guard's *key* is the schema. Task 2 must not drop `required` from any spec. Pinned by a new test. | 2 |
| 2 | `voice-agent` tool dispatch — `factory.py:226` `dict(params.arguments)` → `dispatch_tool_call` → `intake_core.tools.handle_tool_call` | pipecat parses arguments; an empty dict reaches `handle_update_answer(args={})` → `_validate_args` → `{"ok": False, "error": "unknown qid: None"}` | **safe by construction**, unnamed but harmless. Out of phase-4 scope (phase 7 owns the voice LLM). Recorded so it is not mistaken for an omission. | — |
| 3 | `workers/.../src/stages/parse_jd.py:32` `raw = response.content[0].text.strip()` → `json.loads` | `llm_core` returns `reply.text == ""` when content is absent (`llm-core/llm_core/client.py:70-74`). `json.loads("")` raises `JSONDecodeError` → `parse_jd.py:37` sets `facts = {}` → `pipeline.py:73` passes `jd_facts={}` into synthesize. The recruiter gets a prefill built from Cortex + form data only, and **`update_process_stage(… "parse_jd", status="completed", output=jd_out)` records it as COMPLETED** (`pipeline.py:60`). | **MODERATE.** Not a fabricated answer, but a silent downgrade recorded as success. Task 4 keeps the fail-soft and makes it *visible*: `{"skipped": False, "parsed": False, "facts": {}}` and `status="completed"` becomes conditional. | 4 |
| 4 | `workers/.../src/stages/synthesize.py:78, 81` `return _empty_answers()` | **THE DANGEROUS ONE, verified line by line.** `pipeline.py:81-88` writes those nine blank answers into **both** `prefilled_answers` *and* `current_answers`, sets `"status": "ready"`, `"process_status": "idle"`, and **`"process_error": None`** — actively clearing a prior error. The recruiter is shown a completed prefill containing nothing, with no error and no retry. This is phase 2's fabricated-`likely_authentic` shape applied to a whole form. | **DANGEROUS.** Task 5 makes the two degraded branches **raise** instead of returning `_empty_answers()`, so `pipeline.py:100-108`'s existing handler writes `process_status: "failed"` + `process_error`. | 5 |

**On "key the guard on the tool schema's own required property":** sites 3 and 4 use **no tools** — `parse_jd` and `synthesize` are JSON-in-prose calls, verified (`messages.create(...)` with no `tools=`). There is no tool schema to key on, and adding one would be a prompt change (spec non-goal). The faithful analogue is the payload's own declared required keys, and `synthesize.py` already has them: `QUESTION_IDS` (`synthesize.py:18-22`) is exactly the "required properties" set. Task 5 keys the guard on it. Stated explicitly so a reviewer does not read the absence of a tool-schema guard as an oversight.

**The distinction Task 5 must preserve:** a *parsed* reply whose nine answers are legitimately all-null is a real answer (an empty JD with no Cortex context genuinely produces it, and `test_pipeline_cold_mode_skips_cortex_queries` scripts it). An *unparseable* or *non-dict* reply is not. Only the second becomes an exception. `_normalize_answer`'s behaviour is untouched.

---

## Expect fixtures that violate their own schemas

Six were found in phase 3 (2 debrief, 4 intake) the moment required-args guards were added. **Fix the fixture; never weaken the guard.**

Two are already visible in this phase's blast radius, both in `workers/intake-context-builder/tests/`:

- `tests/test_pipeline.py:19` and `:55` script `synthesize_answers` returning `{f"q{i}_x": {...}}` — keys like `q1_x`, `q2_x`, which are **not** in `QUESTION_IDS`. They pass today only because `synthesize_answers` is patched out wholesale. If Task 5's guard is ever wired at the pipeline level rather than inside the stage, these break. Fix the fixture to real qids.
- `tests/test_pipeline.py:19` also uses `"confidence"` where the contract is `"extraction_confidence"` — the legacy key `_normalize_answer` defensively folds. Same treatment.

Neither is load-bearing for this plan as written, but they are the exact shape that has cost this effort time five times. Fix them in Task 5.

---

## Call-site inventory

| # | File | What changes | Anthropic shape it carries today | Task |
|---|---|---|---|---|
| 1 | `voice-agent/src/pipeline/factory.py` | tool-schema reader **extracted** to a tested module, then flipped | `t["name"]` ×2 (`:95`, `:232`), `t.get("input_schema", …)` ×2 (`:97`, `:98`) | 1, 2 |
| 2 | `voice-agent/tests/pipeline/test_tool_schemas.py` | **new** — the test that does not exist today | — | 1 |
| 3 | `intake-core/intake_core/tools/schemas.py` | OpenAI shape becomes canonical; `_as_openai_tool` + `ALL_TOOLS` **deleted** | `input_schema` ×2 (`:22`, `:56`) | 2 |
| 4 | `intake-core/intake_core/screening/tools.py` | OpenAI shape; docstring rewritten | `input_schema` ×1 (`:12`) | 2 |
| 5 | `intake-core/intake_core/tools/__init__.py` | `INTAKE_TOOLS_ANTHROPIC` deleted; `INTAKE_TOOLS` is the one export | `:9`, `:15`, `:82` | 2 |
| 6 | `voice-agent/scripts/smoke_test_v2.py` | `t['name']` → the new reader | `:56-57` | 2 |
| 7 | `intake-core/tests/test_tool_schemas.py` | 7 tests → 8; the phase-3 sentinel **replaced**, not deleted | `input_schema` ×4 | 2 |
| 8 | `intake-core/tests/test_screening_builder.py` | `test_all_screening_tools_shape` rewritten in place | `input_schema` ×1 (`:86`) | 2 |
| 9 | `backend/tests/services/intake/test_intake_tool_export.py` | 2 tests, one **replaced**; net zero | reads `INTAKE_TOOLS_ANTHROPIC` | 2 |
| 10 | `llm-core/llm_core/client.py` | gains `LLMClient.aclose()` | — | 3 |
| 11 | `workers/.../src/clients/llm.py` | **new** — per-invocation gateway client + closer | — | 4 |
| 12 | `workers/.../src/stages/parse_jd.py` | `messages.create` → `llm.complete`; stops reading `content[0].text` | `:9`, `:24`, `:32` | 4 |
| 13 | `workers/.../src/stages/synthesize.py` | same, **plus the dangerous-default guard** | `:9`, `:65`, `:72` | 5 |
| 14 | `workers/.../src/clients/anthropic.py` | **deleted** | whole file | 5 |
| 15 | `workers/.../src/settings.py`, `requirements.txt`, `src/pipeline.py` | `anthropic_*` settings and the `anthropic==0.40.0` pin removed | `:12-13`, `:26-27` / `:1` | 4, 5 |
| 16 | `workers/.../production/Dockerfile`, `deploy/ecr-push.sh` | B5 — build context moved to the repo root | — | 6 |

**Every reader of intake-core's tool schemas, found by repo-wide grep (`ALL_TOOLS`, `ALL_TOOLS_OPENAI`, `INTAKE_TOOLS_*`, `ALL_SCREENING_TOOLS`, `MARK_QUESTION_COVERED`, `UPDATE_ANSWER_TOOL`, `MARK_STATUS_TOOL`, `input_schema`):**

*Production:* `intake-core/intake_core/tools/__init__.py:9`; `intake-core/intake_core/screening/__init__.py:14-18`; `backend/app/services/intake/text_runner.py:25, 42, 280`; `voice-agent/src/main.py:43, 46, 1859, 2195`; `voice-agent/src/pipeline/factory.py:95, 97, 98, 232`.
*Scripts:* `voice-agent/scripts/smoke_test_v2.py:34, 56, 57`.
*Tests:* `intake-core/tests/test_tool_schemas.py`; `intake-core/tests/test_screening_builder.py:81-90`; `backend/tests/services/intake/test_intake_tool_export.py`.
*Name-dispatchers (read the tool CALL, not the schema — unaffected):* `intake_core/tools/__init__.py:32-33, 60-61` (`tool_call.get("name")` / `.get("input")`); `voice-agent/src/pipeline/tool_dispatch.py`; `backend/app/services/intake/text_runner.py` (`tc["name"]` on `stream_llm_turn` events). **These read llm-core's / pipecat's event shape, which this phase does not change. Confirmed by inspection, not assumed.**

---

## Global Constraints

- **Backend must stay at exactly 2185 passed / 5 skipped** (`make test`, repo root, `--cov-fail-under=85`). Task 2 edits `backend/tests/services/intake/test_intake_tool_export.py`, replacing one test with another — **net zero**, by design. No other task touches `backend/`. A task that moves this number has done something the plan did not authorise.
- **`intake-core` is baked into the backend image** (`backend/Dockerfile.test:18`, `backend/Dockerfile:14`). `make test` rebuilds `Dockerfile.test` itself so it picks the change up, **but a running `backend` container does not** — Task 2 must run `docker compose up -d --build backend` or the live service imports a stale copy. Same for `voice-agent` (`voice-agent/Dockerfile:28`) and `intake-context-builder` (`workers/intake-context-builder/Dockerfile:13`). CHECKPOINT fact #4.
- **`intake-core`'s own suite is NOT in `make test`.** Exact command, run from the repo root:
  ```bash
  python3 -m venv /tmp/p4-intake && /tmp/p4-intake/bin/pip install -q -e ./intake-core "pytest>=8,<9" "pytest-asyncio>=0.23,<1.0" "pytest-mock>=3.12" \
    && (cd intake-core && /tmp/p4-intake/bin/python -m pytest -q)
  ```
  **Current: 84 passed** (84 test functions across 14 files, counted at HEAD; matches CHECKPOINT). Paste the new count in every commit that touches `intake-core/`.
- **`workers/intake-context-builder`'s suite** has no Makefile target, no CI, no `conftest.py`, no pytest config, and **`pytest-asyncio` is in no requirements file** (`requirements.txt` is 5 lines: anthropic, supabase, structlog, httpx, pydantic; there is no `requirements-dev.txt`). Its tests carry explicit `@pytest.mark.asyncio`. Exact command:
  ```bash
  python3 -m venv /tmp/p4-icb && /tmp/p4-icb/bin/pip install -q -r workers/intake-context-builder/requirements.txt -e ./intake-core -e ./llm-core "pytest>=8,<9" "pytest-asyncio>=0.23,<1.0" \
    && (cd workers/intake-context-builder && /tmp/p4-icb/bin/python -m pytest -q)
  ```
  **Current: 18 test functions** across 5 test files (`tests/test_pipeline.py` 2, `tests/stages/test_check_context.py` 4, `test_parse_jd.py` 3, `test_query_cortex.py` 3, `test_synthesize.py` 6). **This count has never been run in this effort — Task 4 Step 0 establishes the real baseline before changing anything.** `tests/__init__.py` exists, so pytest's rootdir insertion puts `workers/intake-context-builder` on `sys.path` and `from src.… import` resolves. Drop `-e ./intake-core` and it fails at `src/pipeline.py:9`.
- **`llm-core`'s suite** (Task 3 only): `cd llm-core && python3 -m pytest -q`. CHECKPOINT records **194 passed, 12 deselected**.
- **`voice-agent` has NO test covering `factory.py`.** `tests/pipeline/test_tool_dispatch.py:53-80` only *simulates* the handler closure against a stub; it never imports `factory`. Verified: `grep -rn "factory\|FunctionSchema\|PipelineConfig" voice-agent/tests/` returns only those two docstring/comment mentions. Task 1 exists to close this. Command: `cd voice-agent && python3 -m pytest -q` (10 test files, 63 test functions; **no pass count has ever been recorded** — Task 1 Step 0 records it). Every `tests/*/conftest.py` stubs pipecat into `sys.modules`, so the suite runs on a host without pipecat.
  - **`make verify` is NOT sufficient verification for voice-agent and must not be presented as such.** It proves the container answers `/health`. `factory.build_pipeline` runs only when a WebRTC peer connects, so a KeyError there leaves `/health` green forever. The three real verifications, in descending strength: (1) Task 1's new unit test, which fails on both the KeyError and the silent-empty-properties variant; (2) `voice-agent/scripts/smoke_test_v2.py` step [4], which exercises the tool schemas live against a real session (phase 3 required running it, and Task 2 updates it); (3) `docker compose up -d --build voice-agent && make verify` as a smoke check only.
- No new runtime dependency for `intake-core` — the tool schemas are plain dicts and import nothing. `intake-core` still does **not** depend on `llm-core` (the coverage tracker takes an injected client). Do not add a dependency.
- Rebuild affected containers after each task: `docker compose up -d --build <service>`. `litellm` is **not** touched — both aliases 4b needs already exist (`context-parse-jd` at `litellm-config.yaml:55`, `context-synthesize` at `:133`, both `anthropic/claude-sonnet-5`, both `supports_function_calling: true`).
- Commit after each task with a meaningful message. **Self-review the diff before committing** (`git diff --cached`).
- No API keys, secrets, certs, or `.env` files may be committed.
- Every HTML element added anywhere in this project must carry a unique `id`. (No UI is added by this plan; the rule is project-wide.)
- No Next.js app is touched, so no `npm run build` is required.

---

## Model alias map

| Site | Model source today | Value today | Becomes | Alias in `litellm-config.yaml` |
|---|---|---|---|---|
| `parse_jd` | `settings.anthropic_model_sonnet` → `src/settings.py:27` `os.getenv("ANTHROPIC_MODEL_SONNET", "claude-sonnet-4-6")`, passed at `src/pipeline.py:59` | `claude-sonnet-4-6` (`.env` does not set `ANTHROPIC_MODEL_SONNET` — verified) | `context-parse-jd` via new `settings.parse_jd_model` | `:55` — exists, sonnet-5 |
| `synthesize` | the same setting, passed at `src/pipeline.py:71` | `claude-sonnet-4-6` | `context-synthesize` via new `settings.synthesize_model` | `:133` — exists, sonnet-5 |

**Two settings, not one, even though one variable feeds both today.** They are separate workloads (2048 vs 4096 `max_tokens`, JD extraction vs nine-answer synthesis) and the deliverable of this migration is that either can be pointed at a local model without dragging the other. `litellm-config.yaml:50-54` documents this exact pairing and its own comment forbids the alternative.

**Do NOT reuse `intake-jd`.** It is HAIKU (`litellm-config.yaml:20-24`) and belongs to the backend's JD extract (`backend/app/config.py` `INTAKE_JD_MODEL`). Pointing `parse_jd` at it looks like a tidy-up and silently re-tiers a sonnet workload onto haiku — which the config file's own header forbids. Recon flagged this as B7; it was settled in commit `502cd84` by adding `context-parse-jd`, already live-verified.

Both aliases inherit phase 1's documented `claude-sonnet-4-6` → `claude-sonnet-5` bump. Tier preserved; version deliberately upgraded, exactly as phases 2 and 3 did.

---

## Suite arithmetic

| after task | suite | change | expected |
|---|---|---|---|
| baseline | backend `make test` | — | **2185 passed, 5 skipped** |
| baseline | `intake-core` | — | **84 passed** |
| baseline | `voice-agent` | — | *unrecorded — Task 1 Step 0 establishes it* |
| baseline | `intake-context-builder` | — | *unrecorded — Task 4 Step 0 establishes it* |
| baseline | `llm-core` | — | **194 passed, 12 deselected** |
| 1 | voice-agent | + `test_tool_schemas.py` (5) | baseline + 5 |
| 2 | backend | 1 test replaced by 1 | **2185 / 5, unchanged** |
| 2 | `intake-core` | `test_tool_schemas.py` 7 → 8 (1 rewritten sentinel becomes 2); `test_screening_builder.py` unchanged at 9 | **85 passed** |
| 2 | voice-agent | rewritten in place | unchanged |
| 3 | `llm-core` | + 3 `aclose` tests | **197 passed, 12 deselected** |
| 4 | icb | `test_parse_jd.py` 3 → 5 | baseline + 2 |
| 5 | icb | `test_synthesize.py` 6 → 8; `test_pipeline.py` 2 → 3 | baseline + 5 (cumulative) |
| 6 | — | no test change | — |

**Every count above except the two "unrecorded" rows was derived by reading source. None of them was run — this is a planning document.** The executor pastes measured counts; if a measured baseline differs from a stated one, the measured value wins and CHECKPOINT gets corrected.

---

## File Structure

| Path | Change | Task |
|---|---|---|
| `voice-agent/src/pipeline/tool_schemas.py` | **new** — the tool-schema reader, extracted and testable | 1 |
| `voice-agent/tests/pipeline/test_tool_schemas.py` | **new** — 5 tests | 1 |
| `voice-agent/src/pipeline/factory.py` | uses the extracted reader | 1 |
| `intake-core/intake_core/tools/schemas.py` | OpenAI canonical; `_as_openai_tool` + `ALL_TOOLS` deleted | 2 |
| `intake-core/intake_core/tools/__init__.py` | one export: `INTAKE_TOOLS` | 2 |
| `intake-core/intake_core/screening/tools.py` | OpenAI shape | 2 |
| `intake-core/intake_core/screening/__init__.py` | unchanged names, new shape | 2 |
| `voice-agent/scripts/smoke_test_v2.py` | reads through the new reader | 2 |
| `llm-core/llm_core/client.py` | `+ LLMClient.aclose()` | 3 |
| `workers/intake-context-builder/src/clients/llm.py` | **new** | 4 |
| `workers/intake-context-builder/src/stages/parse_jd.py` | `llm.complete` | 4 |
| `workers/intake-context-builder/src/stages/synthesize.py` | `llm.complete` + guard | 5 |
| `workers/intake-context-builder/src/clients/anthropic.py` | **deleted** | 5 |
| `workers/intake-context-builder/src/settings.py` | `anthropic_*` → `parse_jd_model` / `synthesize_model` | 4, 5 |
| `workers/intake-context-builder/requirements.txt` | `anthropic==0.40.0` removed | 5 |
| `workers/intake-context-builder/production/Dockerfile`, `deploy/ecr-push.sh` | B5 | 6 |

---

### Task 1: Give `voice-agent`'s tool-schema reader a test, before anything can break it

Task 2 changes the shape of the dicts `factory.py` reads, at four call sites in two files. **There is no test in this repo that would notice.** Building the test first is not ceremony: it is the only thing standing between the flip and a silent intake agent, and phase 3 explicitly deferred this work to phase 4.

This task changes **no behaviour**. It extracts the two inline readers into one named module that still reads the *current* Anthropic shape, and pins that shape with tests. Task 2 then flips the module and the tests together, and the tests fail loudly if the flip is wrong.

**Files:**
- Create: `voice-agent/src/pipeline/tool_schemas.py`
- Create: `voice-agent/tests/pipeline/test_tool_schemas.py`
- Modify: `voice-agent/src/pipeline/factory.py`

**Interfaces:**
- Produces: `tool_name(spec: dict) -> str`, `function_schemas(specs: list[dict]) -> list[FunctionSchema]`, and `UnsupportedToolSchema(ValueError)`.
- Consumes: `pipecat.adapters.schemas.function_schema.FunctionSchema`.

- [ ] **Step 0: Record the voice-agent baseline (it has never been recorded)**

```bash
cd voice-agent && python3 -m pytest -q
```

Write the exact line into the task notes. If it is not green at HEAD, **stop and report** — do not build on an unknown baseline. Every `tests/*/conftest.py` stubs pipecat into `sys.modules`, so this runs without pipecat installed.

- [ ] **Step 1: Write the failing test**

Create `voice-agent/tests/pipeline/test_tool_schemas.py`:

```python
"""The reader that turns intake-core tool specs into pipecat FunctionSchemas.

This file exists because nothing else in this repo tested it. factory.py read
`t["name"]` and `t["input_schema"]` inline at four sites across two files, and
intake-core is about to change that shape (phase 4). A wrong flip has two
outcomes and BOTH are silent from the outside:

* KeyError inside build_pipeline — the container's /health stays green forever,
  because build_pipeline only runs when a WebRTC peer connects;
* FunctionSchema(properties={}, required=[]) — the model is handed parameterless
  tools and the intake agent quietly stops recording any answer at all.

So the assertions here are deliberately about the VALUES that reach pipecat, not
merely that the call did not raise.

pipecat is stubbed into sys.modules by tests/screening/conftest.py's pattern, so
FunctionSchema is a MagicMock here and its kwargs are inspected via call_args.
That is enough: what is being tested is this repo's translation, not pipecat's
constructor.
"""
import sys
from unittest.mock import MagicMock

import pytest

for _name in (
    "pipecat",
    "pipecat.adapters",
    "pipecat.adapters.schemas",
    "pipecat.adapters.schemas.function_schema",
):
    sys.modules.setdefault(_name, MagicMock())

from intake_core.screening import ALL_SCREENING_TOOLS  # noqa: E402
from intake_core.tools import INTAKE_TOOLS_ANTHROPIC  # noqa: E402

from src.pipeline.tool_schemas import (  # noqa: E402
    UnsupportedToolSchema,
    function_schemas,
    tool_name,
)


def _kwargs_of(schemas):
    """The kwargs each FunctionSchema was constructed with, in order."""
    from pipecat.adapters.schemas.function_schema import FunctionSchema

    return [call.kwargs for call in FunctionSchema.call_args_list[-len(schemas):]]


def test_every_intake_tool_yields_a_name():
    assert [tool_name(t) for t in INTAKE_TOOLS_ANTHROPIC] == [
        "update_answer",
        "mark_status",
    ]


def test_every_screening_tool_yields_a_name():
    assert [tool_name(t) for t in ALL_SCREENING_TOOLS] == ["mark_question_covered"]


def test_properties_are_never_empty_for_the_intake_tools():
    """The silent-failure guard. A tool handed to the model with no properties
    cannot be called with arguments, so update_answer would record nothing and
    nothing anywhere would raise."""
    schemas = function_schemas(INTAKE_TOOLS_ANTHROPIC)
    for kwargs in _kwargs_of(schemas):
        assert kwargs["properties"], kwargs["name"]
        assert "qid" in kwargs["properties"], kwargs["name"]
        assert kwargs["required"], kwargs["name"]


def test_properties_are_never_empty_for_the_screening_tool():
    schemas = function_schemas(ALL_SCREENING_TOOLS)
    kwargs = _kwargs_of(schemas)[0]
    assert kwargs["name"] == "mark_question_covered"
    assert "question_id" in kwargs["properties"]
    assert kwargs["required"] == ["question_id"]


def test_an_unrecognised_spec_shape_is_refused_by_name():
    """Not a tolerant reader. A spec this module does not recognise must raise
    where it is read, not degrade into an empty-properties tool downstream."""
    with pytest.raises(UnsupportedToolSchema) as exc:
        function_schemas([{"nonsense": True}])
    assert "nonsense" in str(exc.value) or "tool spec" in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd voice-agent && python3 -m pytest -q tests/pipeline/test_tool_schemas.py
```
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pipeline.tool_schemas'` at collection.

- [ ] **Step 3: Write the reader**

Create `voice-agent/src/pipeline/tool_schemas.py`:

```python
"""Turn intake-core tool specs into pipecat FunctionSchemas.

Extracted from factory.py, which read the spec dicts inline at four sites across
two files (build_pipeline's schema construction and its register_function loop,
plus scripts/smoke_test_v2.py). Four inline readers of one wire format is four
places a shape change has to be found by hand, and intake-core's shape is
changing. One named reader with tests is one place.

Deliberately NOT tolerant of multiple shapes. A reader that accepts both the
Anthropic and OpenAI forms would accept a stale spec forever and render it as a
parameterless tool — the model then cannot pass arguments, update_answer records
nothing, and no error is raised anywhere. Refusing an unrecognised spec by name
is the whole point.
"""

from __future__ import annotations

from typing import Any

from pipecat.adapters.schemas.function_schema import FunctionSchema


class UnsupportedToolSchema(ValueError):
    """A tool spec was not in the shape this reader accepts."""


def _body(spec: dict[str, Any]) -> dict[str, Any]:
    if "name" in spec and "input_schema" in spec:
        return spec
    raise UnsupportedToolSchema(
        f"unrecognised tool spec: keys={sorted(spec)!r}; "
        "expected an intake-core tool spec"
    )


def tool_name(spec: dict[str, Any]) -> str:
    return _body(spec)["name"]


def function_schemas(specs: list[dict[str, Any]]) -> list[FunctionSchema]:
    schemas = []
    for spec in specs:
        body = _body(spec)
        parameters = body.get("input_schema") or {}
        schemas.append(
            FunctionSchema(
                name=body["name"],
                description=body.get("description", ""),
                properties=parameters.get("properties", {}),
                required=parameters.get("required", []),
            )
        )
    return schemas
```

- [ ] **Step 4: Point `factory.py` at it**

In `voice-agent/src/pipeline/factory.py`, add to the imports beside the other `src.pipeline` imports (after `:27`):

```python
from src.pipeline.tool_schemas import function_schemas, tool_name
```

Replace `:92-103`:

```python
        if config.tools:
            standard_tools = [
                FunctionSchema(
                    name=t["name"],
                    description=t.get("description", ""),
                    properties=t.get("input_schema", {}).get("properties", {}),
                    required=t.get("input_schema", {}).get("required", []),
                )
                for t in config.tools
            ]
            tools_schema = ToolsSchema(standard_tools=standard_tools)
            context = LLMContext(messages, tools=tools_schema)
```

with:

```python
        if config.tools:
            tools_schema = ToolsSchema(standard_tools=function_schemas(config.tools))
            context = LLMContext(messages, tools=tools_schema)
```

Replace `:231-233`:

```python
            for tool in config.tools:
                tool_name = tool["name"]
                llm.register_function(tool_name, _make_tool_handler(tool_name, _persist_proc_ref))
```

with:

```python
            for tool in config.tools:
                name = tool_name(tool)
                llm.register_function(name, _make_tool_handler(name, _persist_proc_ref))
```

**Note the shadowing.** The old loop bound a local `tool_name`; the new module-level function has the same name. Renaming the local to `name` is required, not cosmetic — leaving it would rebind the imported function after the first iteration and raise `TypeError: 'str' object is not callable` on the second tool. That is exactly the kind of two-tools-only bug a one-tool screening pipeline would never surface.

`FunctionSchema` is now imported only by `tool_schemas.py`; remove the now-unused `from pipecat.adapters.schemas.function_schema import FunctionSchema` at `factory.py:15`. Keep the `ToolsSchema` import at `:14`.

- [ ] **Step 5: Run the suite**

```bash
cd voice-agent && python3 -m pytest -q
```
Expected: PASS at the Step 0 baseline **+5**. Paste the count.

- [ ] **Step 6: Self-review and commit**

```bash
git diff
git add voice-agent/src/pipeline/tool_schemas.py voice-agent/tests/pipeline/test_tool_schemas.py voice-agent/src/pipeline/factory.py
git diff --cached
git commit -m "test(voice-agent): put the intake tool-schema reader behind a test before phase 4 flips it"
```

---

### Task 2: Make the OpenAI tool shape canonical in `intake-core`, and flip every reader in the same commit

**These cannot be split, and the coupling is wider than blocker B2 records.** `factory.py` reads `config.tools` generically for *both* voice pipelines: `main.py:2195` passes `ALL_TOOLS`, `main.py:1859` passes `ALL_SCREENING_TOOLS`. Flipping `tools/schemas.py` alone moves the KeyError from the intake pipeline to the screening pipeline. Flipping `factory.py` alone breaks both immediately. **One commit: both intake-core modules, the reader, the smoke test, and all three test files.**

`intake-core` has no `llm-core` dependency and gains none — these are plain dicts.

**Files:**
- Modify: `intake-core/intake_core/tools/schemas.py`, `intake-core/intake_core/tools/__init__.py`, `intake-core/intake_core/screening/tools.py`
- Modify: `voice-agent/src/pipeline/tool_schemas.py`, `voice-agent/scripts/smoke_test_v2.py`
- Test: `intake-core/tests/test_tool_schemas.py`, `intake-core/tests/test_screening_builder.py`, `voice-agent/tests/pipeline/test_tool_schemas.py`, `backend/tests/services/intake/test_intake_tool_export.py`

**Interfaces:**
- Produces: `intake_core.tools.schemas.ALL_TOOLS_OPENAI` (canonical, and the only list), re-exported as `intake_core.tools.INTAKE_TOOLS`; `intake_core.screening.tools.ALL_SCREENING_TOOLS` in the same shape.
- Removes: `_as_openai_tool`, `ALL_TOOLS`, `INTAKE_TOOLS_ANTHROPIC`.

- [ ] **Step 1: Rewrite `intake-core/tests/test_tool_schemas.py` (the failing test)**

Replace the whole file. Note what happens to the phase-3 sentinel: `test_the_anthropic_export_is_untouched_for_the_voice_agent` is **replaced by two tests, not deleted**. It existed to stop the Anthropic export being removed by accident while `voice-agent` still needed it. Phase 4 removes it *on purpose*, so the property it protected is retired — but its *job* (nobody may silently change what voice-agent consumes) transfers to `voice-agent/tests/pipeline/test_tool_schemas.py`, which Task 1 created and which is a strictly better home for it because it tests the actual reader. What replaces it here is the invariant that survives: exactly one shape, and every spec carries the `required` list the backend's degraded-reply guard is keyed on.

```python
"""Validate tool schemas conform to the OpenAI function-calling shape.

Phase 4 made this shape canonical and deleted the Anthropic one. Two of the
tests below replace the phase-3 sentinel
`test_the_anthropic_export_is_untouched_for_the_voice_agent`, which existed to
stop the Anthropic list being removed while voice-agent still consumed it:

* `test_exactly_one_shape_is_exported` is its inverse — the Anthropic export
  must now be GONE, and must not creep back;
* `test_every_spec_declares_its_required_properties` pins the key the backend's
  degraded-reply guard is built on (backend/app/services/intake/text_runner.py
  reads spec["function"]["parameters"]["required"] to decide whether a truncated
  tool call is dispatched). Drop `required` from a spec and that guard silently
  becomes a no-op.

The reader-side property the sentinel really protected — that voice-agent can
still consume these — now lives in voice-agent/tests/pipeline/test_tool_schemas.py,
against the actual reader rather than against a shape assertion.
"""

from intake_core.tools import schemas as schemas_module
from intake_core.tools.schemas import (
    ALL_TOOLS_OPENAI,
    MARK_STATUS_TOOL,
    UPDATE_ANSWER_TOOL,
)


def test_update_answer_tool_shape():
    t = UPDATE_ANSWER_TOOL
    assert t["type"] == "function"
    fn = t["function"]
    assert fn["name"] == "update_answer"
    assert "description" in fn and len(fn["description"]) > 20
    schema = fn["parameters"]
    assert schema["type"] == "object"
    props = schema["properties"]
    assert set(props.keys()) >= {"qid", "text", "confidence"}
    assert "qid" in schema["required"]
    assert "text" in schema["required"]
    assert "confidence" in schema["required"]
    assert set(props["confidence"]["enum"]) == {"none", "low", "medium", "high"}


def test_mark_status_tool_shape():
    fn = MARK_STATUS_TOOL["function"]
    assert fn["name"] == "mark_status"
    schema = fn["parameters"]
    assert set(schema["properties"]["status"]["enum"]) == {
        "untouched", "needs_probe", "discussed", "validated", "skipped"
    }
    assert "qid" in schema["required"]
    assert "status" in schema["required"]


def test_all_tools_is_list_of_two():
    assert isinstance(ALL_TOOLS_OPENAI, list)
    assert len(ALL_TOOLS_OPENAI) == 2
    names = {t["function"]["name"] for t in ALL_TOOLS_OPENAI}
    assert names == {"update_answer", "mark_status"}


def test_qid_enum_lists_nine_questions():
    """qid parameter should be constrained to the 9 known question IDs."""
    expected = {
        "q1_role_overview", "q2_rounds", "q3_focus_areas", "q4_must_haves",
        "q5_nice_to_haves", "q6_cultural_fit", "q7_team_structure",
        "q8_red_flags", "q9_anything_else",
    }
    for tool in ALL_TOOLS_OPENAI:
        assert set(tool["function"]["parameters"]["properties"]["qid"]["enum"]) == expected


def test_the_qid_enum_is_still_computed_from_the_question_bank():
    """The enum comes from INTAKE_QUESTIONS, not a hand-typed list. That is why
    these specs are not literal_eval-able and why the phase-3 derivation shared
    objects rather than copying them."""
    from intake_core.questions import INTAKE_QUESTIONS

    for tool in ALL_TOOLS_OPENAI:
        enum = tool["function"]["parameters"]["properties"]["qid"]["enum"]
        assert enum == [q["id"] for q in INTAKE_QUESTIONS]


def test_exactly_one_shape_is_exported():
    """Replaces the phase-3 sentinel, inverted. The Anthropic export and the
    function that derived the OpenAI one are both gone, and no spec carries
    `input_schema` or a top-level `name`."""
    assert not hasattr(schemas_module, "ALL_TOOLS")
    assert not hasattr(schemas_module, "_as_openai_tool")
    for tool in ALL_TOOLS_OPENAI:
        assert set(tool) == {"type", "function"}
        assert set(tool["function"]) == {"name", "description", "parameters"}
        assert "input_schema" not in tool["function"]


def test_every_spec_declares_its_required_properties():
    """The key the backend's truncated-tool-call guard is built on. A truncated
    reply arrives as arguments={} (llm-core client.py:501-511); text_runner
    refuses to dispatch it by diffing against this list. An empty `required`
    here turns that guard into a no-op with nothing failing."""
    for tool in ALL_TOOLS_OPENAI:
        required = tool["function"]["parameters"].get("required")
        assert required, tool["function"]["name"]
        props = tool["function"]["parameters"]["properties"]
        assert set(required) <= set(props), tool["function"]["name"]
```

- [ ] **Step 2: Rewrite the screening assertion in `intake-core/tests/test_screening_builder.py`**

Replace `test_all_screening_tools_shape` (`:80-90`) in place — the file's other 8 tests are untouched:

```python
def test_all_screening_tools_shape():
    assert isinstance(ALL_SCREENING_TOOLS, list)
    assert len(ALL_SCREENING_TOOLS) == 1
    tool = ALL_SCREENING_TOOLS[0]
    assert tool["type"] == "function"
    fn = tool["function"]
    assert fn["name"] == "mark_question_covered"
    assert "description" in fn and len(fn["description"]) > 20
    schema = fn["parameters"]
    assert schema["type"] == "object"
    assert "question_id" in schema["properties"]
    assert "question_id" in schema["required"]
```

- [ ] **Step 3: Run both tests to verify they fail**

```bash
python3 -m venv /tmp/p4-intake && /tmp/p4-intake/bin/pip install -q -e ./intake-core "pytest>=8,<9" "pytest-asyncio>=0.23,<1.0" "pytest-mock>=3.12"
(cd intake-core && /tmp/p4-intake/bin/python -m pytest -q)
```
Expected: FAIL — `ImportError: cannot import name 'ALL_TOOLS_OPENAI'`… no: `ALL_TOOLS_OPENAI` still exists at HEAD, so expect **assertion failures** in `test_update_answer_tool_shape` (`t["type"]` KeyError), `test_exactly_one_shape_is_exported` (`ALL_TOOLS` still present), and `test_all_screening_tools_shape`.

- [ ] **Step 4: Flip `intake-core/intake_core/tools/schemas.py`**

Rewrite the module. The two spec bodies **move**, they are not retyped: cut the existing `input_schema` dict literal, paste it under `parameters`, and change nothing inside it. `_QID_ENUM` stays exactly as it is at `:12`.

Header, replacing `:1-6`:

```python
"""Tool-use schemas for update_answer + mark_status, in the OpenAI function shape.

This is the only shape intake-core exports. It is what llm_core accepts
(llm_core/emulation.py rejects Anthropic `input_schema` outright rather than
translating it) and what voice-agent's pipeline reader consumes
(voice-agent/src/pipeline/tool_schemas.py).

The dual shape phase 3 shipped — an Anthropic `ALL_TOOLS` plus a derived
`ALL_TOOLS_OPENAI` sharing schema objects — is gone. It existed for exactly one
reason: voice-agent handed the Anthropic list straight to pipecat and no test
covered that path. That path is now read through a tested module, so the second
shape has no consumer and carrying it would only be an invitation to send it
somewhere.
"""
```

Then `UPDATE_ANSWER_TOOL` becomes:

```python
UPDATE_ANSWER_TOOL = {
    "type": "function",
    "function": {
        "name": "update_answer",
        "description": (
            ... unchanged, moved verbatim from the old top-level "description" ...
        ),
        "parameters": {
            ... unchanged, moved verbatim from the old "input_schema" ...
        },
    },
}
```

and `MARK_STATUS_TOOL` the same. Then, replacing `:72` and `:75-104` entirely:

```python
ALL_TOOLS_OPENAI: list[dict] = [UPDATE_ANSWER_TOOL, MARK_STATUS_TOOL]
```

**Delete `_as_openai_tool` and `ALL_TOOLS`. Delete the "TEMPORARY DUAL SHAPE" comment block** — it named phase 4 as its owner and phase 4 is executing it.

**How to prove the specs were MOVED, not retyped.** Phase 3 established that these specs share objects, so before touching anything, capture identity from the pre-flip module and compare afterwards. Run this **before Step 4 edits anything** and again after:

```bash
# BEFORE the edit, from the repo root:
/tmp/p4-intake/bin/python - <<'PY' > /tmp/p4-specs-before.json
import json
from intake_core.tools.schemas import ALL_TOOLS
json.dump([{"name": t["name"], "description": t["description"],
            "parameters": t["input_schema"]} for t in ALL_TOOLS],
          __import__("sys").stdout, sort_keys=True, indent=2)
PY

# AFTER the edit (reinstall so the change is picked up):
/tmp/p4-intake/bin/pip install -q -e ./intake-core
/tmp/p4-intake/bin/python - <<'PY' > /tmp/p4-specs-after.json
import json
from intake_core.tools.schemas import ALL_TOOLS_OPENAI
json.dump([t["function"] for t in ALL_TOOLS_OPENAI],
          __import__("sys").stdout, sort_keys=True, indent=2)
PY

diff /tmp/p4-specs-before.json /tmp/p4-specs-after.json && echo "SPECS MOVED, NOT RETYPED"
```

**The `diff` must be empty.** A `git diff` of `schemas.py` cannot show this, because re-nesting under `function` reindents every line of both specs. This is CHECKPOINT fact #7 applied: these specs are not `literal_eval`-able (`_QID_ENUM` is a computed `Name`), so the comparison must go through a real import, which is what the script above does. Paste the `SPECS MOVED, NOT RETYPED` line in the commit body.

*(Phase 3's `is`-identity proof retires with the derivation: after this task there is only one list, so there is no second object to be identical to. The import-and-diff above is its replacement and is what "proven moved not retyped" means from here on.)*

- [ ] **Step 5: Flip `intake-core/intake_core/screening/tools.py`**

```python
"""Tool-use schema + handler for the screening agent, in the OpenAI function shape.

Same shape as intake_core.tools.schemas, so voice-agent consumes
ALL_SCREENING_TOOLS exactly like ALL_TOOLS_OPENAI — through the same reader
(voice-agent/src/pipeline/tool_schemas.py), which is why the two modules have to
change together: factory.build_pipeline reads config.tools generically and both
voice pipelines pass through it.
"""

from __future__ import annotations

MARK_QUESTION_COVERED = {
    "type": "function",
    "function": {
        "name": "mark_question_covered",
        "description": "Mark a screening question as sufficiently answered.",
        "parameters": {
            "type": "object",
            "properties": {"question_id": {"type": "string"}},
            "required": ["question_id"],
        },
    },
}
ALL_SCREENING_TOOLS = [MARK_QUESTION_COVERED]


def handle_mark_question_covered(state: dict, question_id: str) -> dict:
    answered = set(state.get("answered", []))
    answered.add(question_id)
    state["answered"] = list(answered)
    return {"ok": True, "answered": state["answered"]}
```

`intake_core/screening/__init__.py` needs no edit — it re-exports names, not shapes.

**Note:** `test_screening_builder.py:85` asserts `len(fn["description"]) > 20`. The current description is 48 characters, so it passes. Verify, do not assume.

- [ ] **Step 6: Collapse the exports in `intake-core/intake_core/tools/__init__.py`**

`:9`:
```python
from intake_core.tools.schemas import ALL_TOOLS_OPENAI
```
`:15-18` become one binding:
```python
# The intake agent's tools, in the only shape intake-core exports. Named without
# a provider in it on purpose: the previous pair (INTAKE_TOOLS_ANTHROPIC /
# INTAKE_TOOLS_OPENAI) existed only while two shapes did.
INTAKE_TOOLS: list[dict] = ALL_TOOLS_OPENAI
```
`:81-86`:
```python
__all__ = [
    "INTAKE_TOOLS",
    "handle_tool_call",
    "ahandle_tool_call",
]
```

**`handle_tool_call` / `ahandle_tool_call` are NOT touched.** They read `tool_call.get("name")` and `tool_call.get("input")` at `:32-33` and `:60-61` — that is the *tool call event* shape (llm-core's `stream_turn` payload and pipecat's dispatch), not the *schema* shape. Verified: `llm-core/llm_core/client.py:458` emits `{"id", "name", "input"}` and phase 3's `text_runner` passes it through unchanged. Changing them here would break both callers for no reason.

- [ ] **Step 7: Flip the voice-agent reader**

In `voice-agent/src/pipeline/tool_schemas.py`, replace `_body`:

```python
def _body(spec: dict[str, Any]) -> dict[str, Any]:
    if spec.get("type") == "function" and isinstance(spec.get("function"), dict):
        return spec["function"]
    raise UnsupportedToolSchema(
        f"unrecognised tool spec: keys={sorted(spec)!r}; expected the OpenAI "
        'function shape {"type": "function", "function": {...}}. Anthropic-shaped '
        "specs (top-level 'name' + 'input_schema') were removed from intake-core "
        "in phase 4 and are not accepted here — see the module docstring for why "
        "this reader is not tolerant."
    )
```

and in `function_schemas`, `parameters = body.get("input_schema") or {}` becomes `parameters = body.get("parameters") or {}`.

Update the module docstring's last paragraph to say the accepted shape is OpenAI.

In `voice-agent/tests/pipeline/test_tool_schemas.py`, change the import at the top from `INTAKE_TOOLS_ANTHROPIC` to `INTAKE_TOOLS`, rename the local uses, and add one test:

```python
def test_an_anthropic_shaped_spec_is_refused(monkeypatch):
    """The shape intake-core used to export. It must raise here rather than
    render as a parameterless tool — see the module docstring."""
    with pytest.raises(UnsupportedToolSchema):
        function_schemas([
            {"name": "update_answer", "input_schema": {"type": "object",
             "properties": {"qid": {"type": "string"}}, "required": ["qid"]}}
        ])
```

*(Task 1's `test_an_unrecognised_spec_shape_is_refused_by_name` stays; this adds the specific regression. voice-agent goes to baseline +6.)*

- [ ] **Step 8: Flip `voice-agent/scripts/smoke_test_v2.py`**

`:34`:
```python
    from intake_core.tools import INTAKE_TOOLS
    from src.pipeline.tool_schemas import tool_name
```
`:56-57`:
```python
    assert {tool_name(t) for t in INTAKE_TOOLS} == {'update_answer', 'mark_status'}
    print(f"    {len(INTAKE_TOOLS)} tools: {[tool_name(t) for t in INTAKE_TOOLS]}")
```

This is the live verification path phase 3 required running; it must not be left reading a shape that no longer exists.

- [ ] **Step 9: Fix the backend test — a replacement, not a deletion**

`backend/tests/services/intake/test_intake_tool_export.py` has 2 tests. `test_the_openai_export_is_accepted_by_llm_core` survives with an import rename. `test_the_two_exports_describe_the_same_two_tools` is retired *because there is no second export* — it is replaced 1-for-1, so `make test` stays at **2185 / 5**:

```python
"""The intake tool specs, in the shape the gateway accepts.

text_runner hands these to llm_core.stream_turn, which REJECTS Anthropic-shaped
specs rather than translating them (llm_core/emulation.py:84-93). This is the
backend-side guard for that; intake-core's own suite (not run by `make test`)
covers the specs themselves.
"""
from llm_core.emulation import validate_tool_shape

import intake_core.tools as intake_tools
from intake_core.tools import INTAKE_TOOLS


def test_the_openai_export_is_accepted_by_llm_core():
    entries = validate_tool_shape(INTAKE_TOOLS)
    assert [name for name, _description, _schema in entries] == [
        "update_answer",
        "mark_status",
    ]


def test_no_anthropic_shaped_export_survives():
    """Replaces test_the_two_exports_describe_the_same_two_tools, which existed
    only while intake-core carried both shapes. The property worth pinning from
    the backend is now the negative one: a reintroduced Anthropic export would
    be accepted by nothing here and rejected by llm_core at runtime, on a path
    make test does not exercise."""
    assert not hasattr(intake_tools, "INTAKE_TOOLS_ANTHROPIC")
    assert len(INTAKE_TOOLS) == 2
    for spec in INTAKE_TOOLS:
        assert set(spec) == {"type", "function"}
```

Also update `backend/app/services/intake/text_runner.py:25` and `:280` — `INTAKE_TOOLS_OPENAI` → `INTAKE_TOOLS`. `:38-48`'s `_REQUIRED_ARGS` comprehension already reads `spec["function"]["parameters"]["required"]` and needs no change; that is exactly the property Step 1's `test_every_spec_declares_its_required_properties` now pins from the other side.

- [ ] **Step 10: Run all four suites**

```bash
/tmp/p4-intake/bin/pip install -q -e ./intake-core
(cd intake-core && /tmp/p4-intake/bin/python -m pytest -q)     # expect 85 passed
(cd voice-agent && python3 -m pytest -q)                        # expect Task 1 baseline +6
make test                                                       # expect 2185 passed, 5 skipped
diff /tmp/p4-specs-before.json /tmp/p4-specs-after.json          # must be empty
```

Then rebuild every image that bakes in `intake-core` — **all three, or they import a stale copy** (CHECKPOINT fact #4):

```bash
docker compose up -d --build backend voice-agent intake-context-builder
make verify
```

`make verify` here is a smoke check, not the verification. **The real live check is:**

```bash
cd voice-agent && python3 scripts/smoke_test_v2.py
```

which needs `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `TEST_SESSION_ID`, and `LLM_GATEWAY_URL=http://localhost:4000` (blocker B14: `.env` does not set `LLM_GATEWAY_URL`, and llm-core's default `http://litellm:4000` is a compose-internal hostname). Step [4] of that script is the tool-schema check. **If it cannot be run in this environment, say so explicitly in the commit — do not substitute `make verify` and call the task verified.**

- [ ] **Step 11: Self-review and commit**

```bash
git add intake-core/intake_core/tools intake-core/intake_core/screening/tools.py \
        intake-core/tests/test_tool_schemas.py intake-core/tests/test_screening_builder.py \
        voice-agent/src/pipeline/tool_schemas.py voice-agent/tests/pipeline/test_tool_schemas.py \
        voice-agent/scripts/smoke_test_v2.py \
        backend/app/services/intake/text_runner.py \
        backend/tests/services/intake/test_intake_tool_export.py
git diff --cached
git commit -m "feat(intake-core)!: make the OpenAI tool shape canonical and delete the Anthropic export"
```

Commit body must carry: all four suite counts, the `SPECS MOVED, NOT RETYPED` line, and whether `smoke_test_v2.py` was run.

**Self-review checklist for this diff specifically:**
- [ ] `grep -rn "input_schema" intake-core/intake_core` returns nothing.
- [ ] `grep -rn "INTAKE_TOOLS_ANTHROPIC\|ALL_TOOLS\b\|_as_openai_tool" --include=*.py .` returns nothing outside `docs/`.
- [ ] `factory.py`'s `register_function` loop uses a local named `name`, not `tool_name` (the shadowing trap in Task 1 Step 4).
- [ ] `handle_tool_call` / `ahandle_tool_call` are byte-identical to HEAD.

---

### Task 3: `llm-core` gains `LLMClient.aclose()`

**Why this is in phase 4 and not deferred.** `workers/intake-context-builder` creates a **fresh event loop per invocation and closes it** — `production/handler.py:28-33` is `loop = asyncio.new_event_loop()` … `loop.close()` in `finally`, and the compose wrapper runs that same handler through `asyncio.to_thread` (`app.py:46`). `src/pipeline.py:110-114`'s `finally` block and `src/clients/anthropic.py:22-30`'s `close_anthropic_client` exist for exactly this reason; the file's own docstring says *"Two invocations on the same warm container must not crash from a closed event loop."*

`llm_core.get_client()` is a **process-global singleton** (`llm-core/llm_core/client.py:530-537`) wrapping one `AsyncOpenAI` built in `__init__` (`:130`). Reusing it across a closed loop is the failure `close_anthropic_client` was written to prevent. And **`LLMClient` has no close method at all** — `grep -n "    def \|    async def " llm-core/llm_core/client.py` returns only `__init__`, `_gateway_get`, `complete`, `stream_turn`, `_to_reply`. So 4b has three options and only one is acceptable: reuse the singleton and inherit a warm-container crash; reach into `client._client` privately; or add a public closer. This task adds the closer.

This is additive, touches no existing behaviour, and is independently shippable.

**Files:**
- Modify: `llm-core/llm_core/client.py`
- Test: `llm-core/tests/test_client_complete.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `llm-core/tests/test_client_complete.py`:

```python
async def test_aclose_closes_the_underlying_client():
    """Lambda-shaped callers build a client per invocation on a fresh event loop
    and must close it in a finally, or the next warm invocation reuses a
    transport bound to a dead loop. workers/intake-context-builder is one; its
    handler.py creates and closes a loop per call."""
    inner = AsyncMock()
    client = LLMClient(openai_client=inner, capabilities=_caps(True))

    await client.aclose()

    inner.close.assert_awaited_once()


async def test_aclose_is_idempotent():
    inner = AsyncMock()
    client = LLMClient(openai_client=inner, capabilities=_caps(True))

    await client.aclose()
    await client.aclose()

    assert inner.close.await_count == 2


async def test_aclose_never_raises_out_of_a_finally_block():
    """It is called from `finally` in every intended caller. A failure closing a
    transport must not replace the exception already unwinding, nor invent one
    where the request itself succeeded."""
    inner = AsyncMock()
    inner.close.side_effect = RuntimeError("event loop is closed")
    client = LLMClient(openai_client=inner, capabilities=_caps(True))

    await client.aclose()  # must not raise
```

Adapt `_caps(True)` to whatever the file's existing capability-stub helper is called — read the file's existing fixtures first; do not invent one.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd llm-core && python3 -m pytest -q tests/test_client_complete.py
```
Expected: FAIL — `AttributeError: 'LLMClient' object has no attribute 'aclose'`.

- [ ] **Step 3: Add the method**

In `llm-core/llm_core/client.py`, after `stream_turn` and before `_to_reply`:

```python
    async def aclose(self) -> None:
        """Release the underlying transport.

        Long-lived services (the backend, voice-agent) use the process singleton
        from get_client() and never call this — the transport lives as long as
        the process and closing it would tear down a shared resource. This exists
        for the Lambda-shaped callers that build a client per invocation on a
        fresh event loop and close that loop afterwards: without it the next warm
        invocation reuses a connection pool bound to a dead loop, which is a
        RuntimeError with a misleading message far from its cause.

        Never raises. Every intended caller invokes it from a `finally`, where an
        exception would replace whatever was already unwinding.
        """
        close = getattr(self._client, "close", None)
        if close is None:
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 — see docstring
            logger.debug("llm_client_close_failed", exc_info=True)
```

`inspect` is already imported at module scope (used by `_close_stream`); confirm before adding an import.

- [ ] **Step 4: Run the suite**

```bash
cd llm-core && python3 -m pytest -q
```
Expected: **197 passed, 12 deselected** (194 + 3). Paste the count.

- [ ] **Step 5: Self-review and commit**

```bash
git add llm-core/llm_core/client.py llm-core/tests/test_client_complete.py
git diff --cached
git commit -m "feat(llm-core): let a per-invocation client release its transport"
```

---

### Task 4: Move `parse_jd` onto the gateway

`src/clients/anthropic.py` stays alive for one more task — `synthesize` still uses it. That keeps every intermediate commit both green and *working*, the same ordering phase 3 used for `anthropic_stream.py`.

**Files:**
- Create: `workers/intake-context-builder/src/clients/llm.py`
- Modify: `workers/intake-context-builder/src/stages/parse_jd.py`, `src/settings.py`, `src/pipeline.py`
- Test: `workers/intake-context-builder/tests/stages/test_parse_jd.py`

- [ ] **Step 0: Record the icb baseline (never recorded)**

```bash
python3 -m venv /tmp/p4-icb && /tmp/p4-icb/bin/pip install -q -r workers/intake-context-builder/requirements.txt -e ./intake-core -e ./llm-core "pytest>=8,<9" "pytest-asyncio>=0.23,<1.0"
(cd workers/intake-context-builder && /tmp/p4-icb/bin/python -m pytest -q)
```

18 test functions are expected to collect. Write the exact pass line into the task notes. **If it is not green at HEAD, stop and report** — this suite has never been run in this effort and a pre-existing failure must not be attributed to the migration.

- [ ] **Step 1: Write the failing test**

Rewrite `workers/intake-context-builder/tests/stages/test_parse_jd.py`. The three existing tests become five; `llm-core`'s `fake_llm` fixture is available automatically through its pytest11 entry point once `llm-core` is installed — no conftest import is needed.

```python
"""Stage 2: parse JD into structured facts."""

import json

import pytest
from llm_core.types import LLMReply

from src.stages.parse_jd import parse_jd


def _reply(text: str) -> LLMReply:
    return LLMReply(text=text, model="context-parse-jd", finish_reason="stop")


@pytest.mark.asyncio
async def test_parse_jd_returns_skipped_when_no_jd(fake_llm):
    out = await parse_jd(llm=fake_llm, model="context-parse-jd", jd_text=None)
    assert out["skipped"] is True
    assert fake_llm.calls == []


@pytest.mark.asyncio
async def test_parse_jd_extracts_structured_facts(fake_llm):
    fake_llm.queue_reply(_reply(json.dumps({
        "must_have_skills": ["Python", "PostgreSQL"],
        "nice_to_have_skills": ["Kafka"],
        "responsibilities": ["build payment infra"],
        "team_signals": ["senior IC role"],
    })))
    out = await parse_jd(llm=fake_llm, model="context-parse-jd", jd_text="...long JD text...")
    assert out["skipped"] is False
    assert out["parsed"] is True
    assert out["facts"]["must_have_skills"] == ["Python", "PostgreSQL"]


@pytest.mark.asyncio
async def test_parse_jd_sends_the_alias_and_no_tools(fake_llm):
    """The alias is context-parse-jd (SONNET). It must never be intake-jd, which
    is HAIKU and belongs to the backend — that swap looks like a tidy-up and
    silently re-tiers this workload."""
    fake_llm.queue_reply(_reply("{}"))
    await parse_jd(llm=fake_llm, model="context-parse-jd", jd_text="JD")
    call = fake_llm.calls[0]
    assert call["model"] == "context-parse-jd"
    assert call["tools"] is None
    assert call["temperature"] == 0
    assert call["max_tokens"] == 2048


@pytest.mark.asyncio
async def test_parse_jd_marks_an_unparseable_reply_as_not_parsed(fake_llm):
    """The fail-soft is kept — a bad JD parse only weakens the synthesize prompt,
    it does not fabricate an answer. What changes is that it stops being
    invisible: `parsed` is False so the pipeline can record the stage honestly
    instead of writing status=completed over a silent downgrade."""
    fake_llm.queue_reply(_reply("not json"))
    out = await parse_jd(llm=fake_llm, model="context-parse-jd", jd_text="JD")
    assert out["skipped"] is False
    assert out["parsed"] is False
    assert out["facts"] == {}


@pytest.mark.asyncio
async def test_parse_jd_treats_an_empty_reply_as_unparsed(fake_llm):
    """llm_core returns reply.text == "" when the provider sent no content
    (client.py:70-74). json.loads("") raises, so this lands in the same branch —
    asserted rather than assumed, because "" is the degraded shape this codebase
    keeps mistaking for an answer."""
    fake_llm.queue_reply(_reply(""))
    out = await parse_jd(llm=fake_llm, model="context-parse-jd", jd_text="JD")
    assert out["parsed"] is False
    assert out["facts"] == {}
```

Check `fake_llm`'s recorded-call key names against `llm-core/llm_core/fake.py` before writing the assertions in `test_parse_jd_sends_the_alias_and_no_tools`; use the names it actually records.

- [ ] **Step 2: Run test to verify it fails**

```bash
(cd workers/intake-context-builder && /tmp/p4-icb/bin/python -m pytest -q tests/stages/test_parse_jd.py)
```
Expected: FAIL — `TypeError: parse_jd() got an unexpected keyword argument 'llm'`.

- [ ] **Step 3: Add the per-invocation gateway client**

Create `workers/intake-context-builder/src/clients/llm.py`:

```python
"""Gateway client wrapper.

Deliberately NOT llm_core.get_client(). That is a process-global singleton
holding one AsyncOpenAI (llm_core/client.py:530-537), and this worker creates a
FRESH EVENT LOOP PER INVOCATION and closes it (production/handler.py:28-33,
called through asyncio.to_thread by app.py). A transport built on invocation
one's loop and reused on invocation two's is the closed-loop crash the
CLAUDE.md Lambda rules exist to prevent — the same reason the Anthropic client
this replaces was created per invocation and closed in run_pipeline's finally.

Mirrors clients/anthropic.py exactly, so the pipeline's finally block does not
change shape.
"""

from __future__ import annotations

from typing import Optional

from llm_core import LLMClient

_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Return the invocation-scoped gateway client. Caller MUST close it in finally."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


async def close_llm_client() -> None:
    """Called from pipeline.run_pipeline's finally block. Resets module global."""
    global _llm_client
    if _llm_client is not None:
        await _llm_client.aclose()
        _llm_client = None
```

`LLMClient()` reads `LLM_GATEWAY_URL` (default `http://litellm:4000`) and `LITELLM_MASTER_KEY` from the environment via `llm_core.settings.get_settings()`. In compose the default hostname is correct and `LITELLM_MASTER_KEY` is already in `.env`; **no `.env` change is needed for the compose path.** For a host-side run, export `LLM_GATEWAY_URL=http://localhost:4000` (blocker B14).

- [ ] **Step 4: Migrate the stage**

`workers/intake-context-builder/src/stages/parse_jd.py`, replacing `:9` and `:16-39`:

```python
"""Stage 2: parse JD into structured facts via the LLM gateway."""

from __future__ import annotations

import json
from typing import Any, Optional

import structlog
from llm_core import LLMClient

from ..prompts.parse_jd import PARSE_JD_SYSTEM_PROMPT, build_parse_jd_user_prompt

logger = structlog.get_logger(__name__)


async def parse_jd(
    llm: LLMClient,
    model: str,
    jd_text: Optional[str],
) -> dict[str, Any]:
    if not jd_text or not jd_text.strip():
        return {"skipped": True, "parsed": False, "facts": {}}

    reply = await llm.complete(
        model=model,
        max_tokens=2048,
        temperature=0,
        system=PARSE_JD_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_parse_jd_user_prompt(jd_text)}],
    )

    # llm_core returns "" rather than None when the provider sent no content
    # (client.py:70-74), so an empty reply falls into the same branch as a
    # malformed one. That is intentional: both are degraded, neither is an answer.
    raw = reply.text.strip()
    try:
        facts = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("jd_parse_unparseable", alias=model, chars=len(raw), raw=raw[:500])
        return {"skipped": False, "parsed": False, "facts": {}}

    if not isinstance(facts, dict):
        logger.warning("jd_parse_not_an_object", alias=model, raw=raw[:500])
        return {"skipped": False, "parsed": False, "facts": {}}

    return {"skipped": False, "parsed": True, "facts": facts}
```

**Why `parsed` is a new key rather than a raise.** A missing JD parse degrades the synthesize prompt; it does not fabricate an answer, so the fail-soft is correct. What was wrong is that `pipeline.py:60` recorded `status="completed"` over it either way. `parsed` makes the downgrade visible in `process_stages` without changing any prompt or blocking the run. Site 4's failure — the one that *does* fabricate — is Task 5's, and it raises.

- [ ] **Step 5: Settings and wiring**

`src/settings.py` — add `parse_jd_model` beside the existing fields (keep `anthropic_api_key` and `anthropic_model_sonnet` for one more task; `synthesize` still needs them):

```python
    parse_jd_model: str
```
```python
        parse_jd_model=os.getenv("PARSE_JD_MODEL", "context-parse-jd"),
```

`src/pipeline.py`:
- `:12` add `from .clients.llm import get_llm_client, close_llm_client` beside the anthropic import.
- `:34` add `llm = get_llm_client()` beside `ant = get_anthropic_client(...)`.
- `:59` becomes:
  ```python
  jd_out = await parse_jd(llm=llm, model=settings.parse_jd_model, jd_text=jd_text)
  ```
- `:110-114`'s `finally` gains `await close_llm_client()` **before** `await close_anthropic_client()`.

`:60`'s `update_process_stage(..., status="completed", output=jd_out)` stays as it is — `jd_out` now carries `parsed`, which is the point.

- [ ] **Step 6: Run the suite**

```bash
(cd workers/intake-context-builder && /tmp/p4-icb/bin/python -m pytest -q)
```
Expected: Step 0 baseline **+2**. Paste the count.

`tests/test_pipeline.py` patches `src.pipeline.parse_jd` wholesale, so it does not see the signature change — but it does **not** patch `src.pipeline.get_llm_client`. Add it to both `with` blocks (`:12-21` and `:48-57`) alongside the existing `patch("src.pipeline.get_anthropic_client")`, or `LLMClient()` will be constructed for real during the test.

- [ ] **Step 7: Rebuild and commit**

```bash
docker compose up -d --build intake-context-builder && make verify
git add workers/intake-context-builder/src workers/intake-context-builder/tests/stages/test_parse_jd.py workers/intake-context-builder/tests/test_pipeline.py
git diff --cached
git commit -m "feat(intake-context-builder): move the JD parse onto the llm-core gateway"
```

---

### Task 5: Move `synthesize` onto the gateway, guard its dangerous default, and delete the Anthropic client

This is the task that closes the effort's most dangerous silent default. Read the degraded-reply table above before starting.

**Files:**
- Modify: `workers/intake-context-builder/src/stages/synthesize.py`, `src/pipeline.py`, `src/settings.py`, `requirements.txt`
- Delete: `workers/intake-context-builder/src/clients/anthropic.py`
- Test: `workers/intake-context-builder/tests/stages/test_synthesize.py`, `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

In `workers/intake-context-builder/tests/stages/test_synthesize.py`, convert all six tests to `fake_llm` and **replace `test_synthesize_returns_all_empty_on_malformed_response` (`:43-52`)**. That test currently *pins the bug*: it asserts the function returns nine blank answers on unparseable JSON, which `pipeline.py:81-88` then writes as `status: "ready"` with `process_error` cleared. It is the exact "fixture encoding the behaviour the guard forbids" shape CHECKPOINT warns about. **Fix the test, never weaken the guard.**

```python
import json

import pytest
from llm_core.types import LLMReply

from src.stages.synthesize import (
    QUESTION_IDS,
    SynthesisUnusable,
    synthesize_answers,
)


def _reply(text: str) -> LLMReply:
    return LLMReply(text=text, model="context-synthesize", finish_reason="stop")


async def _run(fake_llm, **kw):
    return await synthesize_answers(
        llm=fake_llm, model="context-synthesize",
        form_data={"role_name": "x"}, jd_facts={}, cortex_data={}, **kw
    )


@pytest.mark.asyncio
async def test_synthesize_raises_on_a_malformed_response(fake_llm):
    """REPLACES test_synthesize_returns_all_empty_on_malformed_response, which
    pinned the bug. Returning _empty_answers() here made pipeline.py:81-88 write
    nine blank answers into prefilled_answers AND current_answers, set
    status="ready" and process_status="idle", and CLEAR process_error — the
    recruiter is shown a finished prefill containing nothing, with no error and
    no retry. Raising lets pipeline.py:100-108 record process_status="failed"."""
    fake_llm.queue_reply(_reply("not json"))
    with pytest.raises(SynthesisUnusable):
        await _run(fake_llm)


@pytest.mark.asyncio
async def test_synthesize_raises_on_an_empty_reply(fake_llm):
    """llm_core yields reply.text == "" when the provider sent no content."""
    fake_llm.queue_reply(_reply(""))
    with pytest.raises(SynthesisUnusable):
        await _run(fake_llm)


@pytest.mark.asyncio
async def test_synthesize_raises_when_the_reply_is_not_an_object(fake_llm):
    fake_llm.queue_reply(_reply('["a", "b"]'))
    with pytest.raises(SynthesisUnusable):
        await _run(fake_llm)


@pytest.mark.asyncio
async def test_synthesize_accepts_a_legitimately_empty_prefill(fake_llm):
    """The distinction the guard must preserve. A PARSED reply whose nine answers
    are all null is a real answer — an empty JD with no Cortex context genuinely
    produces it, and test_pipeline_cold_mode_skips_cortex_queries scripts it.
    Only unparseable / non-object replies are degraded."""
    payload = {q: {"text": None, "extraction_confidence": "none", "sources": []} for q in QUESTION_IDS}
    fake_llm.queue_reply(_reply(json.dumps(payload)))
    out = await _run(fake_llm)
    assert len(out) == 9
    assert all(a["extraction_confidence"] == "none" for a in out.values())
```

Keep `test_synthesize_returns_all_nine_keys`, `test_synthesize_normalizes_legacy_confidence_key`, `test_synthesize_normalizes_string_sources`, `test_synthesize_rejects_invalid_confidence`, `test_synthesize_handles_non_dict_answer` — convert each to `fake_llm.queue_reply(_reply(json.dumps(...)))` and the `llm=`/`model=` kwargs. `_normalize_answer` is **not** changed, so all five keep asserting exactly what they assert today. 6 → 8.

Also fix the two schema-violating fixtures in `tests/test_pipeline.py:19` and `:55`: replace `{f"q{i}_x": ...}` with real `QUESTION_IDS` keys and `"confidence"` with `"extraction_confidence"`, and add a third test:

```python
@pytest.mark.asyncio
async def test_pipeline_records_failure_when_synthesis_is_unusable():
    """The guard's payoff, at the level that matters. A degraded synthesis must
    never reach the update that sets status="ready" and clears process_error."""
    ...  # patch synthesize_answers to raise SynthesisUnusable
    result = await run_pipeline(session_id="abc", include_turns=False)
    assert result["status"] == "failed"
    update_kwargs = [c.args[0] for c in mock_sb.table.return_value.update.call_args_list]
    assert not any(u.get("status") == "ready" for u in update_kwargs)
    assert any(u.get("process_status") == "failed" for u in update_kwargs)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
(cd workers/intake-context-builder && /tmp/p4-icb/bin/python -m pytest -q)
```
Expected: FAIL — `ImportError: cannot import name 'SynthesisUnusable'`.

- [ ] **Step 3: Migrate the stage and add the guard**

`workers/intake-context-builder/src/stages/synthesize.py` — `:9` and `:58-86`:

```python
import structlog
from llm_core import LLMClient
```

```python
class SynthesisUnusable(RuntimeError):
    """The model's reply could not be read as a nine-answer object.

    Raised rather than returning _empty_answers(), which was the pre-phase-4
    behaviour and the most dangerous default in this codebase. pipeline.py writes
    whatever this returns into BOTH prefilled_answers and current_answers, sets
    status="ready" and process_status="idle", and clears process_error — so nine
    blank answers were presented to the recruiter as a completed prefill, with the
    previous run's error wiped and nothing to retry from. Raising routes the same
    condition into pipeline.py's existing handler, which records
    process_status="failed" with the message.

    Note what is NOT raised: a reply that PARSES into an object whose nine answers
    are all null. That is a real (if thin) answer — an empty JD with no Cortex
    context produces it legitimately — and _normalize_answer still handles it.
    Only unparseable and non-object replies are degraded.
    """


async def synthesize_answers(
    llm: LLMClient,
    model: str,
    form_data: dict[str, Any],
    jd_facts: dict[str, Any],
    cortex_data: dict[str, Any],
) -> dict[str, Any]:
    reply = await llm.complete(
        model=model,
        max_tokens=4096,
        temperature=0,
        system=SYNTHESIZE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_synthesize_user_prompt(form_data, jd_facts, cortex_data)}],
    )
    raw = _strip_markdown_fence(reply.text.strip())
    try:
        answers = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("synthesize_unparseable", alias=model, chars=len(raw), raw=raw[:500])
        raise SynthesisUnusable(
            f"synthesis reply was not JSON ({len(raw)} chars)"
        ) from exc

    if not isinstance(answers, dict):
        logger.warning("synthesize_not_an_object", alias=model, raw=raw[:500])
        raise SynthesisUnusable(
            f"synthesis reply was a {type(answers).__name__}, expected an object"
        )

    normalized = {}
    for qid in QUESTION_IDS:
        normalized[qid] = _normalize_answer(answers.get(qid))
    return normalized
```

`_empty_answers()` now has no caller. **Delete it** rather than leaving a function whose only purpose was the bug — a live `_empty_answers` is an invitation for the next person to reinstate the fail-soft.

`_normalize_answer` and `_strip_markdown_fence` are unchanged.

- [ ] **Step 4: Wire it and delete the Anthropic client**

`src/pipeline.py`:
- delete `:12` (`from .clients.anthropic import …`)
- delete `:34` (`ant = get_anthropic_client(...)`)
- `:69-75`:
  ```python
  answers = await synthesize_answers(
      llm=llm,
      model=settings.synthesize_model,
      form_data=form_data,
      jd_facts=jd_out.get("facts", {}),
      cortex_data=cortex_out,
  )
  ```
- delete `await close_anthropic_client()` from the `finally`.

`src/settings.py`: delete `anthropic_api_key` and `anthropic_model_sonnet` (both the field and the `load_settings` line — note `anthropic_api_key` reads `os.environ["ANTHROPIC_API_KEY"]`, i.e. it is **required today and stops being required**), add:
```python
    synthesize_model: str
```
```python
        synthesize_model=os.getenv("SYNTHESIZE_MODEL", "context-synthesize"),
```

`requirements.txt`: delete `:1` (`anthropic==0.40.0`).

```bash
git rm workers/intake-context-builder/src/clients/anthropic.py
```

- [ ] **Step 5: Run the suite and verify the SDK is gone from the image**

```bash
(cd workers/intake-context-builder && /tmp/p4-icb/bin/python -m pytest -q)
docker compose up -d --build intake-context-builder
docker compose exec intake-context-builder python -c "import anthropic" ; echo "exit=$?"
grep -rn "anthropic" workers/intake-context-builder/src workers/intake-context-builder/requirements.txt
```

Expected: suite at Task 4's count **+5**; the `import anthropic` must fail with `ModuleNotFoundError` and print a non-zero exit; the `grep` must return nothing. **`intake-core` no longer pins `anthropic` (phase 3 removed it), so nothing reinstalls it transitively — but verify, do not assume: that exact assumption cost phase 3 a debugging cycle.**

- [ ] **Step 6: Self-review and commit**

```bash
docker compose up -d --build intake-context-builder && make verify
git add -A workers/intake-context-builder
git diff --cached
git commit -m "feat(intake-context-builder): move synthesis onto the gateway and stop shipping a blank prefill as success"
```

---

### Task 6: Blocker B5 — make the Lambda image buildable, or record that it is dead

`workers/intake-context-builder/deploy/ecr-push.sh:26` does `cd "$(dirname "$0")/.."` and `:61` builds `-f production/Dockerfile .`, so the context is `workers/intake-context-builder/` and `llm-core` at the repo root is invisible. **That path is already broken independently of this migration:** `production/Dockerfile:11` copies `intake-core-pkg/`, which does not exist in the tree and is gitignored at `.gitignore:5`.

**This task has a decision gate.** The compose service is the live path (`docker-compose.yml:200-212`, reached through `JOB_INVOKER` + `CONTEXT_BUILDER_WORKER_URL` in `.env`). Settle whether the Lambda is still deployed before writing code:

```bash
aws lambda get-function --function-name intake-agent-context-builder --region us-west-1 >/dev/null 2>&1 \
  && echo "LAMBDA LIVE" || echo "LAMBDA ABSENT OR NO CREDENTIALS"
```

- **If absent / decommissioned:** delete `production/Dockerfile` and `deploy/ecr-push.sh`, and say so in the commit. Do **not** delete `production/handler.py` or `production/__init__.py` — `app.py:22` imports the handler and the compose service runs it.
- **If live, or if it cannot be determined:** fix the build context. `deploy/ecr-push.sh:26` → `cd "$(dirname "$0")/../../.."`, `:61` → `-f workers/intake-context-builder/production/Dockerfile .`, and `production/Dockerfile` becomes:

```dockerfile
FROM public.ecr.aws/lambda/python:3.11

COPY workers/intake-context-builder/requirements.txt .
RUN pip install -r requirements.txt

# Shared packages, installed from the working tree so they match this checkout —
# the same treatment the compose Dockerfile gives them. This replaces a
# `COPY intake-core-pkg/` of a directory that does not exist in the tree and is
# gitignored, i.e. this deploy path could not previously be built from a clean
# checkout at all.
COPY intake-core /tmp/intake-core
RUN pip install --no-cache-dir /tmp/intake-core && rm -rf /tmp/intake-core
COPY llm-core /tmp/llm-core
RUN pip install --no-cache-dir /tmp/llm-core && rm -rf /tmp/llm-core

COPY workers/intake-context-builder/src/ ${LAMBDA_TASK_ROOT}/src/
COPY workers/intake-context-builder/production/ ${LAMBDA_TASK_ROOT}/production/

CMD ["production.handler.handler"]
```

Note `production/handler.py:13` does `sys.path.insert(0, "/var/task/src")`; that is unaffected. Also update the env-var list printed at `deploy/ecr-push.sh`'s tail: `ANTHROPIC_API_KEY` is no longer read by this worker, `LLM_GATEWAY_URL` and `LITELLM_MASTER_KEY` are.

- [ ] **Step 1: Settle the decision gate and record the answer in the commit body.**
- [ ] **Step 2: Apply whichever branch applies.**
- [ ] **Step 3: Verify.** If the image path was kept:
  ```bash
  docker build --platform linux/amd64 -f workers/intake-context-builder/production/Dockerfile -t icb-lambda-test .
  ```
  Expected: builds clean. **This is the first time this image has been buildable from a clean checkout.** Do not push it — building is the verification; deployment is the operator's call.
- [ ] **Step 4: Commit**
  ```bash
  git add workers/intake-context-builder/production workers/intake-context-builder/deploy
  git diff --cached
  git commit -m "fix(intake-context-builder): build the Lambda image from the repo root so it can see the shared packages"
  ```

**Not fixed here:** the same B5 wound in `workers/feedback-agent` and `workers/intake-agent`. Those belong to phases 5-6, whose plan should reuse whatever decision this task records.

---

## Definition of done for this plan

- `grep -rn "input_schema" intake-core/intake_core workers/` returns nothing.
- `grep -rn "ALL_TOOLS\b\|INTAKE_TOOLS_ANTHROPIC\|INTAKE_TOOLS_OPENAI\|_as_openai_tool" --include=*.py .` returns nothing outside `docs/`.
- `grep -rn "anthropic" workers/intake-context-builder/src workers/intake-context-builder/requirements.txt` returns nothing; `workers/intake-context-builder/src/clients/anthropic.py` does not exist; `docker compose exec intake-context-builder python -c "import anthropic"` fails with `ModuleNotFoundError`.
- Backend `make test` green at **2185 passed, 5 skipped**, unchanged from the phase-3 baseline. Any other number means the plan was exceeded.
- `intake-core` green at **85 passed** (84 + 1), count pasted in Task 2's commit.
- `voice-agent` green at its Task-1 Step-0 baseline **+6**, both counts pasted. `voice-agent/tests/pipeline/test_tool_schemas.py` exists and fails if a tool reaches pipecat with empty `properties` — the silent-failure mode that had no test before this phase.
- `llm-core` green at **197 passed, 12 deselected**.
- `intake-context-builder` green at its Task-4 Step-0 baseline **+7**, both counts pasted.
- The two intake tool specs and the one screening spec are proven **MOVED, not retyped**: `diff /tmp/p4-specs-before.json /tmp/p4-specs-after.json` is empty, and the `SPECS MOVED, NOT RETYPED` line is in Task 2's commit body. (Phase 3's `is`-identity proof retires with the derivation it proved — after this phase there is only one list, so there is no second object to be identical to.)
- Every migrated call site has a stated answer to "what does an empty reply produce": `parse_jd` returns `parsed: False` and logs with a distinct event; `synthesize` raises `SynthesisUnusable` and can no longer write `status: "ready"` with `process_error` cleared; the intake tool specs still carry `required`, pinned by `test_every_spec_declares_its_required_properties`, which is the key `text_runner._missing_args` is built on.
- Two model settings hold aliases (`PARSE_JD_MODEL` → `context-parse-jd`, `SYNTHESIZE_MODEL` → `context-synthesize`), both sonnet, neither reusing the haiku `intake-jd`. `litellm-config.yaml` is **unchanged** — both aliases already exist and were live-verified in commit `502cd84`.
- `docker compose up -d --build backend voice-agent intake-context-builder && make verify` shows all ten services `ok`. Recorded as a smoke check, **not** as verification of `factory.py`.
- `voice-agent/scripts/smoke_test_v2.py` runs green, or the commit says explicitly that it could not be run and why.
- B5 settled: either the Lambda path builds from the repo root, or it is deleted with the decision recorded.
- `.superpowers/sdd/CHECKPOINT.md` updated: phase 4 DONE; new baselines for `intake-core` (85), `llm-core` (197), `voice-agent`, `intake-context-builder`; blocker B2 closed; B5 settled for this worker and still open for two; the four corrections below folded into the record.

## What recon and the spec got wrong — verified against source at HEAD

1. **Recon B2 undercounts the readers.** It names `factory.py:92-103`. There are four: `factory.py:95`, `:97-98`, **`factory.py:232`** (the `register_function` loop — named by neither recon nor CHECKPOINT), and `voice-agent/scripts/smoke_test_v2.py:56-57`.
2. **Recon B2 misses the screening coupling entirely.** `factory.build_pipeline` reads `config.tools` generically and `main.py:1859` passes `ALL_SCREENING_TOOLS` through it. `tools/schemas.py` and `screening/tools.py` cannot be flipped in separate commits. Recon's option (c), "export both shapes for one phase", would not have helped — it was already the phase-3 state.
3. **Recon's failure-mode call was backwards, as CHECKPOINT records** — `t["name"]` KeyErrors before the empty-`properties` path is reached. Confirmed again here. The silent variant is only reachable via the half-move this plan forbids.
4. **Recon B7 and the alias table are stale.** `context-parse-jd` is no longer missing (`litellm-config.yaml:55`, added in `502cd84`, sonnet-5). The "missing coverage-tracker alias" row was already withdrawn by CHECKPOINT.
5. **Recon's voice-agent test-file count is off by one** — 10 test files (63 test functions), not 11.
6. **The spec's `intake-core` row is partly already done.** "Drop the `anthropic` dependency" and "`coverage_tracker.py:81` moves to `llm.complete`" both landed in phase 3. Only the two schema modules remain.
7. **Neither the spec nor recon notices the event-loop hazard in 4b.** `production/handler.py:28-33` creates and closes a loop per invocation, and `llm_core.get_client()` is a process-global singleton with **no close method at all**. Naively swapping `get_anthropic_client` for `get_client` reintroduces the exact warm-container crash `close_anthropic_client`'s docstring says it exists to prevent. Task 3 adds `LLMClient.aclose()`; Task 4 builds the client per invocation.

## Carried forward

- **B5 is still open for `workers/feedback-agent` and `workers/intake-agent`** (phases 5-6). Task 6's decision should be reused, not re-litigated.
- **B15: `intake-context-builder` has no `depends_on: litellm`** (`docker-compose.yml:200-212`; only `backend` has one, at `:158`). It will race the gateway on `make up`. Not fixed here because the worker is invoked on demand rather than at boot, so the race is not reachable in practice — but it is one `depends_on` away from being correct and phases 5-6 hit the same thing for three services.
- **B14: `.env` has no `LLM_GATEWAY_URL`.** Harmless in compose (llm-core defaults to `http://litellm:4000`) and wrong for any host-side run. Every host-side command in this plan exports it.
- **`voice-agent` still has no end-to-end test of `build_pipeline`.** Task 1 tests the tool-schema reader, which is the part phase 4 changes; the rest of the factory remains uncovered and `make verify` will not notice. Phase 7 rewrites more of this file and should widen the coverage rather than inherit the gap.
- **`intake_core.tools.handle_tool_call` still dispatches on `{"name", "input"}`.** Recon called the dict shape "an Anthropic artifact and a decision point". It is not: `llm-core/llm_core/client.py:458` emits exactly that shape on the streaming path, and pipecat supplies the same fields on the voice path. It is the *event* contract, not a provider shape, and it is deliberately untouched.
