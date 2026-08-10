# Worker LLM Gateway Migration Implementation Plan (Phases 5 + 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `workers/feedback-agent` and `workers/intake-agent` off `api.anthropic.com` and onto the LiteLLM gateway, so that after this phase neither worker contains the string `api.anthropic.com`, neither names a provider model id, and every one of the twelve production call sites either gets a real answer or fails loudly — never a plausible-looking default built from an empty reply.

**Architecture:** Both workers own a HAND-ROLLED `httpx` client (`src/clients/anthropic.py`), not the Anthropic SDK. The two files are near-identical: same class, same retry loop, same `resp_json["content"][0]["text"]` read; intake-agent adds an unreachable `cached_prefix` parameter. Neither worker sends `tools`. Neither streams. Every call is a single user message in, one string out. The migration is therefore a **wire repoint**, not a rewrite: the endpoint, the auth header, the model field and the response path change; the call-site surface (`call_haiku` / `call_sonnet`) does not. The dangerous part is not the wire — it is that this codebase's fifth instance of "a degraded reply lands on a default that reads as a real answer" is sitting in `feedback-agent`, and phase 5 is the first thing that has ever tested those paths at all.

**Tech Stack:** Python 3.11, `httpx`, `pydantic-settings`, `structlog`, pytest + pytest-asyncio (explicit `@pytest.mark.asyncio`, no `asyncio_mode`), Docker Compose, LiteLLM proxy.

**Source spec:** `docs/superpowers/specs/2026-08-07-provider-agnostic-llm-design.md` §Per-service migration rows for `workers/feedback-agent` (`:205`) and `workers/intake-agent` (`:206`)
**Recon:** `.superpowers/sdd/phases-4-7-recon.md` §PHASE 5, §PHASE 6, blockers B5, B6, B8, B9, B13, B14, B15
**Live state:** `.superpowers/sdd/CHECKPOINT.md` — its HARD-WON FACTS are binding here, especially fact #3.
**Prior phase, and the format this plan follows:** `docs/superpowers/plans/2026-08-10-phase3-backend-streaming.md`

---

## The decision this plan turns on: repoint `httpx`, do NOT adopt `llm-core`

**Recommendation: repoint the existing `httpx` client. Do not add `llm-core` to either worker.**

**The deciding reason, verified at source: blocker B5 is REAL, and the httpx repoint is the only option that does not break the Lambda deploy path.**

```
workers/feedback-agent/deploy/ecr-push.sh:25   cd "$(dirname "$0")/.."
workers/feedback-agent/deploy/ecr-push.sh:53   docker build --platform linux/amd64 -t "${REPO_NAME}:latest" -f production/Dockerfile .
workers/intake-agent/deploy/ecr-push.sh:26     cd "$(dirname "$0")/.."
workers/intake-agent/deploy/ecr-push.sh:55     docker build --platform linux/amd64 -t "${REPO_NAME}:latest" -f production/Dockerfile .
```

The `.` after `cd "$(dirname "$0")/.."` makes the build context `workers/<name>/`. `llm-core` lives at the repo root and is **not inside that context**, so `workers/feedback-agent/production/Dockerfile` (13 lines, `COPY src/` + `COPY production/`) and `workers/intake-agent/production/Dockerfile` (9 lines, same) **physically cannot `COPY llm-core`**. Adopting `llm-core` would force, inside this phase, a rewrite of two `ecr-push.sh` build contexts and two Lambda Dockerfiles for a deploy path nobody has confirmed is still live (recon OPEN/UNKNOWN #1) — and the equivalent wound already exists unfixed next door, where `workers/intake-context-builder/production/Dockerfile` vendors an `intake-core-pkg/` directory that does not exist in the tree.

**And the thing being bought is nothing.** Verified by grep across both workers: zero occurrences of `input_schema`, `"tools"`, `tool_choice`, or `tool_use` outside tests. No worker sends a tool spec; no worker streams; every request is `messages=[{"role":"user","content":prompt}]`. `llm_core`'s entire value proposition here — tool-shape validation, `tool_call_named`, emulated-tool JSON, the streaming contract, forced `tool_choice` — is inert. What is actually needed is a URL, a `Bearer` header, and `choices[0].message.content`.

The compose images could take `llm-core` (they build from the repo root: `docker-compose.yml` gives `context: .` for both, and `workers/feedback-agent/Dockerfile:15` copies `workers/feedback-agent/src/`). The Lambda images cannot. Adopting it would leave the two build paths structurally different, which is worse than either alternative.

**The spec agrees** (`:205`, "Repoint the existing httpx client at the proxy with an OpenAI-shaped payload"). This plan follows it, with the evidence above as the reason rather than deference.

**What is given up, and the replacement:** `llm-core` centralises the empty-reply guard (`_first_choice`, `client.py:50-60`) and the `fake_llm` pytest fixture. Both are replaced here at a cost of ~25 lines: Task 2 puts a single `_read_content` choke point in each worker's client that raises `EmptyLLMReply` rather than returning `""`, and Task 1 gives each worker a real test image so the guard can be tested with `unittest.mock` against a fake `httpx` response — no new dependency.

---

## Corrections to recon and to the spec — every claim below re-verified at source

Recon has been wrong three times on this effort. Everything it asserts about phases 5 and 6 was re-checked; here is what changed.

| Claim | Source | Verdict |
|---|---|---|
| **B5** — worker Lambda Dockerfiles cannot see `llm-core` | recon | **REAL.** `workers/feedback-agent/deploy/ecr-push.sh:25,53`; `workers/intake-agent/deploy/ecr-push.sh:26,55`. **But it does not block this plan** — see the decision above. It stays open for phase 4b. |
| **B6** — a second client at `src/api/server.py:271`, `requests`, hardcoded model, 9 call sites | recon | **REAL, every number exact.** `def call_sonnet` at `:271`; `import requests` at `:14`; `os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")` at `:272`; `"model": "claude-sonnet-4-6"` at `:282`; `requests.post` at `:287`; `response.json()["content"][0]["text"]` at `:294`. Call sites: `316, 405, 481, 505, 597, 637, 658, 790, 906` — 9, exactly as listed. |
| **B6 addendum, NEW — recon said "migrate it, or delete it" without evidence for either.** | this plan | `src/api/server.py` is a **strict subset duplicate of `local/api/`**. Its six routes (`/map-topics`, `/process-feedback`, `/process-complete`, `/extract-evidence`, `/judge-feedback`, `/health`) all exist under `local/api/routes/`, which additionally serves `/rounds`. `workers/feedback-agent/docker-compose.yml:37` runs `streamlit run local/ui/round_tester.py`; nothing anywhere runs `src/api/server.py` or `src/ui/`. `src/ui/*.py` differ from `local/ui/*.py` by 6 diff lines each (`API_URL` gained an `os.getenv`). Both landed in the same commit, `255c049`. **Recommendation: DELETE, do not migrate** (Task 4). |
| `requests` is not installable in the shipped image | recon | **CONFIRMED.** `requests` appears in neither `requirements.txt` nor `production/requirements.txt`; only `types-requests>=2.31.0` in `requirements-dev.txt`. `src/api/server.py` cannot import in the compose image, which installs `production/requirements.txt` (`workers/feedback-agent/Dockerfile:11`). |
| **B9** — `call_haiku_sync` / `call_sonnet_sync` are dead | recon | **CONFIRMED.** `src/clients/anthropic.py:133` and `:161`. Grep for both names across the entire repo (`*.py`, `*.md`, `*.txt`) returns **only those two definition lines**. Each opens its own `httpx.Client` straight at `api.anthropic.com`. Delete (Task 2). |
| **B8** — intake-agent's ternary is `:40-44`, not the spec's `:41-43` | recon | **CONFIRMED.** `model_id = (` at `:40`, `)` at `:44`. |
| **B8** — intake-agent `call_haiku` has zero callers | recon | **CONFIRMED.** `src/clients/anthropic.py:122`; grep across `workers/intake-agent/` finds the definition and its own body, nothing else. |
| `cached_prefix` is never passed | recon | **CONFIRMED.** Declared at `:37`, consumed at `:53-56` and `:65`, forwarded at `:122-123` and `:125-126`. No caller in `src/pipeline.py`, `production/handler.py`, `local/api/`, or `tests/` ever passes it. The `cache_control: {"type": "ephemeral"}` block at `:55` is unreachable. |
| **B10** — `workers/feedback-agent/tests` has zero Anthropic-shaped tests | recon | **CONFIRMED, and stronger than recon states.** Across all 7 test files there is exactly ONE reference to any LLM-calling module: `tests/test_orchestrator_holistic.py:17` imports `FeedbackOrchestrator` — and `:59-60` `monkeypatch.setattr(orch, "process_complete", ...)` replaces the only method that reaches the client. **Not one test in this worker has ever executed a line of `src/clients/anthropic.py`.** |
| intake-agent tests stub at method level | recon | **CONFIRMED.** `tests/test_pipeline.py:52,206` and `tests/test_screenable_flag.py:63` set `anthropic.call_sonnet.side_effect` on a bare `AsyncMock()`; `tests/test_handler_warm.py:53,76` `patch("production.handler.AnthropicClient")`. They survive a wire repoint that keeps the method names — but `AnthropicClient` is patched **by string**, so a class rename costs exactly 2 test edits. |
| **B13** — no CI, no Makefile target for these suites | recon | **CONFIRMED.** `Makefile` targets: `up, down, build, logs, ps, verify, test, test-cortex, verify-local-llm`. `.github/workflows/gate.yml` has two `run:` steps, both greps (brand references, captured data). No test job. **Task 1 closes this for these two workers.** |
| **B14** — `LLM_GATEWAY_URL` absent from `.env` | recon | **CONFIRMED.** `.env` defines `LITELLM_MASTER_KEY` and `LLM_FORCE_JSON_TOOLS` but **not** `LLM_GATEWAY_URL`; `.env.example:129` documents it. |
| **B15** — the workers do not `depends_on: litellm` | recon | **CONFIRMED.** `docker-compose.yml` — `backend` has `depends_on: [feedback-agent, intake-agent, intake-context-builder, litellm]`; `feedback-agent` and `intake-agent` have no `depends_on` at all. |
| **B7 / feedback-condense** — orphan alias | recon | **CONFIRMED orphan** (`litellm-config.yaml:127`, sonnet-5). See "The two orphan aliases" below for the recommendation. |
| Spec `:206` cites `src/clients/anthropic.py:41-43` | spec | **WRONG**, see B8. Cite `:40-44`. |
| Spec §Testing "workers/intake-agent/tests (3 …)" but lists four filenames | spec | **3 files is right** (`test_handler_warm.py`, `test_pipeline.py`, `test_screenable_flag.py`), plus `tests/__init__.py`. |
| Spec: feedback-agent is "the existing httpx client" (singular) | spec | **WRONG** — there are two clients and three dead entry points. See B6, B9. |
| **NEW, missed by both** — `workers/feedback-agent/tests/` has **no `__init__.py`**, `workers/intake-agent/tests/` **has one** | this plan | This is why the run command must be `python -m pytest` and not bare `pytest` for feedback-agent: with no `tests/__init__.py` and no `conftest.py` anywhere, pytest inserts `tests/` on `sys.path`, not the worker root, so `from src.services.orchestrator import ...` (`test_orchestrator_holistic.py:17`) resolves only because `python -m` puts CWD on `sys.path`. |
| **NEW, missed by both** — running feedback-agent's suite on a bare host is not possible | this plan | `tests/test_orchestrator_holistic.py:17` → `src.services.orchestrator` → `InterviewPipeline` → `EmbeddingService` → `sentence-transformers` + `torch`. Task 1 therefore runs it in a container, as `make test` does for the backend. |

---

## Global Constraints

- Python `>=3.11`. **No new runtime dependency in either worker.** `httpx>=0.27.0` is already in `workers/feedback-agent/production/requirements.txt:24` and `workers/intake-agent/production/requirements.txt:1`; that is the only client library this plan needs. Two new **test-only** dependencies (`pytest`, `pytest-asyncio`) are installed inside the new test images, never into a production image.
- **The backend must stay at 2185 passed / 5 skipped.** Nothing in this plan touches `backend/`, `intake-core/`, `llm-core/`, or `voice-agent/`. Confirm it anyway, once, in Task 7: `make test` from the repo root, and paste the count. If it moved, this plan did something it did not intend to and the task does not ship.
- **Acceptance bar, every task:** the affected worker's suite green, count pasted. Baselines are established and pasted in Task 1 and are the only numbers this plan is allowed to compare against. Static counts of `def test_` at HEAD (no `parametrize` anywhere in either suite, so the collected count should match): **feedback-agent 34** (`test_fixture_schema` 3, `test_models_new_fields` 6, `test_normalize_fixture` 11, `test_orchestrator_holistic` 1, `test_result_transformer` 3, `test_runner` 4, `test_supabase_feedback_source` 6); **intake-agent 14** (`test_handler_warm` 3, `test_pipeline` 6, `test_screenable_flag` 5). **Do not trust these two numbers — Task 1 measures them.** No test may be deleted or weakened, and no new skip may be introduced. One bounded exception: Task 4 deletes `src/api/server.py`, which has no tests.
- **Expect fixtures that violate their own contract.** Six were found in phase 3 the moment required-args guards were added. Task 3 adds required-key guards to six feedback-agent parse sites, and `workers/feedback-agent/evals/` and `tests/test_fixture_schema.py` / `test_normalize_fixture.py` carry recorded LLM payloads. **When a guard fires on a fixture: fix the fixture, never weaken the guard.** If a fixture genuinely records a degraded production reply, that is the bug the guard exists to find — record it in the commit message.
- Rebuild affected containers after changes: `docker compose up -d --build feedback-agent` and `docker compose up -d --build intake-agent`. The feedback image carries torch + sentence-transformers and is ~1.4 GB; its first rebuild is slow. Task 7 also changes `docker-compose.yml` and `litellm-config.yaml`; the proxy reads its config at boot, so `docker compose up -d litellm` is required for a config edit to exist.
- Commit after each task with a meaningful message. **Self-review the staged diff before committing** (`git diff --cached`).
- No API keys, secrets, certs, or `.env` files may be committed. `LITELLM_MASTER_KEY` is read from the environment; it must never appear in a source file, a test, or a log line. `.env.example` documents names with empty values only.
- Every HTML element added anywhere in this project must carry a unique `id`. (No UI is added; the rule is project-wide.)
- Run `npm run build` before committing any change touching a Next.js app. (None is touched.)
- **No prompt text changes.** A spec non-goal. `src/prompts/` is read-only for this plan.

---

## Call-site inventory — 2 workers, 2 clients, 12 production sites, 9 dev-only sites, 3 dead entry points

| # | File:line | Method | Tier today | Becomes | Tools? | Streams? | Task |
|---|---|---|---|---|---|---|---|
| **F1** | `feedback-agent/src/services/feedback.py:49` / `:52` | `call_sonnet` (feedback_extract) | sonnet | `feedback-sonnet` | no | no | 2, 3 |
| **F2** | `feedback-agent/src/services/feedback.py:107` / `:110` | `call_sonnet` (feedback_condense) | sonnet | `feedback-sonnet` | no | no | 2, 3 |
| **F3** | `feedback-agent/src/services/interview.py:103` / `:106` | `call_sonnet` (topic_mapping) | sonnet | `feedback-sonnet` | no | no | 2 |
| **F4** | `feedback-agent/src/services/interview.py:135` / `:138` | `call_haiku` (participant_detection, segments) | **haiku** | `feedback-haiku` | no | no | 2, 3 |
| **F5** | `feedback-agent/src/services/interview.py:151` / `:154` | `call_haiku` (participant_detection, fallback) | **haiku** | `feedback-haiku` | no | no | 2, 3 |
| **F6** | `feedback-agent/src/services/judge.py:76` (client at `:21`) | `call_sonnet` (judge) | sonnet | `feedback-sonnet` | no | no | 2, 3 |
| **F7** | `feedback-agent/src/services/summary.py:98` (client at `:23`) | `call_sonnet` (question_summary) | sonnet | `feedback-sonnet` | no | no | 2, 3 |
| **F8** | `feedback-agent/src/services/summary.py:161` (client at `:41`) | `call_sonnet` (round_summary) | sonnet | `feedback-sonnet` | no | no | 2 |
| **F9** | `feedback-agent/src/services/evidence.py:154` (client at `:70`) | `call_sonnet` (evidence_extraction) | sonnet | `feedback-sonnet` | no | no | 2, 3 |
| **F10** | `feedback-agent/src/services/verdict.py:44` / `:47` | `call_haiku` (verdict_extraction) | **haiku** | `feedback-haiku` | no | no | 2, 3 |
| — | `feedback-agent/src/services/orchestrator.py:47` | constructs the client, injects it | — | — | — | — | 2 |
| — | `feedback-agent/local/api/routes/topics.py:6` | imports the class (dev route) | — | — | — | — | 2 |
| **I1** | `intake-agent/src/pipeline.py:100` | `call_sonnet` (rounds, `max_tokens=4096`) | sonnet | `intake-agent-sonnet` | no | no | 5, 6 |
| **I2** | `intake-agent/src/pipeline.py:120` | `call_sonnet` (round details, `max_tokens=2048`) | sonnet | `intake-agent-sonnet` | no | no | 5, 6 |
| — | `intake-agent/production/handler.py:64` | constructs the client, injects it | — | — | — | — | 5 |
| **DEV** | `feedback-agent/src/api/server.py:271` def; called at `:316, 405, 481, 505, 597, 637, 658, 790, 906` | own `call_sonnet` via `requests`, hardcoded `claude-sonnet-4-6` at `:282` | sonnet | **deleted** | no | no | 4 |
| **DEAD** | `feedback-agent/src/clients/anthropic.py:133` | `call_haiku_sync` | haiku | **deleted** | — | — | 2 |
| **DEAD** | `feedback-agent/src/clients/anthropic.py:161` | `call_sonnet_sync` | sonnet | **deleted** | — | — | 2 |
| **DEAD** | `intake-agent/src/clients/anthropic.py:122` | `call_haiku` — zero callers | haiku | `intake-agent-haiku` (**migrated, kept**) | — | — | 5 |
| **DEAD** | `intake-agent/src/clients/anthropic.py:37,53-56,65` | `cached_prefix` — never passed | — | **deleted** | — | — | 5 |

Each `:NN` / `:NN` pair in the F-rows is **one logical site with two branches** — an injected-client branch and an `async with AnthropicClient() as c:` fallback. Both branches call the same method with the same prompt; the migration changes neither branch's shape.

### Do these workers use tools? **No. Verified, and this is why the plan has no schema-conversion task.**

```
grep -rn 'input_schema\|"tools"\|tool_choice\|tool_use' --include='*.py' workers/feedback-agent workers/intake-agent   →   (no matches outside tests)
```

Every request built by either client is exactly:

```python
payload = {
    "model": model_id,
    "max_tokens": max_tokens,
    "temperature": 0,
    "messages": [{"role": "user", "content": prompt}],
}
```

(`feedback-agent/src/clients/anthropic.py:45-50`, `intake-agent/src/clients/anthropic.py:46-51`.) Every one of those four keys is **already valid OpenAI Chat Completions**. There is no Anthropic `system` array, no `tools`, no content blocks. Consequently:

- There is **no `input_schema` → `{"type":"function","function":{...}}`** conversion to perform in either worker, so there is nothing for a "moved, not retyped" dict-equality proof to prove, and no `literal_eval` / `exec` question to answer. CHECKPOINT fact #7's technique does not apply to this phase. **This is a real finding, not an omission** — Task 2 Step 1 pins it with a test that fails if either worker ever starts sending `tools`, so the absence stays true.
- The only Anthropic-wire-specific construct in either file is intake-agent's unreachable `cached_prefix` block (`:53-56`), which builds `system=[{"type":"text","text":...,"cache_control":{"type":"ephemeral"}}]`. It is deleted rather than translated — see Task 5.
- The one thing that *does* change shape is the **response**: `resp_json["content"][0]["text"]` → `resp_json["choices"][0]["message"]["content"]`, and the usage counters `input_tokens`/`output_tokens` → `prompt_tokens`/`completion_tokens`.

---

## Model alias map — tier is part of the contract

`litellm-config.yaml`'s header (`:10-15`) is explicit: *"MODEL TIER IS PART OF THE CONTRACT. An alias must resolve to the same tier the call site uses today, or the migration silently re-prices and re-times a workload while claiming to be a no-op."* Here is the full accounting.

| Call sites | Model source today | Value today | Alias | Alias resolves to | Tier check |
|---|---|---|---|---|---|
| F1, F2, F3, F6, F7, F8, F9 | `Settings.anthropic_model_sonnet` (`feedback-agent/src/config/settings.py:12`) | `claude-sonnet-4-6` | `feedback-sonnet` | `anthropic/claude-sonnet-5` (`litellm-config.yaml:154-158`) | **sonnet → sonnet.** Version bump 4-6 → 5 is phase 1's documented deliberate upgrade. |
| F4, F5, F10 | `Settings.anthropic_model_haiku` (`:11`) | `claude-haiku-4-5-20251001` | `feedback-haiku` | `anthropic/claude-haiku-4-5-20251001` (`:148-152`) | **haiku → haiku, byte-identical model id.** |
| I1, I2 | `Settings.anthropic_model_sonnet` (`intake-agent/src/config/settings.py:12`) | `claude-sonnet-4-6` | `intake-agent-sonnet` | `anthropic/claude-sonnet-5` (`:166-170`) | **sonnet → sonnet.** Same documented bump. |
| intake-agent `call_haiku` (no caller) | `Settings.anthropic_model_haiku` (`:11`) | `claude-haiku-4-5-20251001` | `intake-agent-haiku` | `anthropic/claude-haiku-4-5-20251001` (`:160-164`) | **haiku → haiku, byte-identical.** No caller either side of the migration; nothing is re-tiered. |
| `src/api/server.py` (9 dev sites) | **hardcoded** at `:282` | `claude-sonnet-4-6` | **none — deleted** | — | Nothing re-tiered; the path is removed. |

**`.env` overrides neither default in either worker** — the var scan of the live `.env` shows `ANTHROPIC_API_KEY` but no `ANTHROPIC_MODEL_HAIKU` / `ANTHROPIC_MODEL_SONNET`, so the class defaults above are what runs in production today. All four aliases already exist; **no new alias is needed and none may be added.**

### The two orphan aliases — explicit recommendations

- **`intake-agent-haiku` (`litellm-config.yaml:160`) — KEEP, and keep `call_haiku` with it.** After the repoint, `call_haiku` is two lines that name a gateway alias; it opens no provider path of its own, which is the only reason dead code mattered here. Keeping it preserves the deliberate file-for-file symmetry with `feedback-agent`, where the identical method has **three** live callers (F4, F5, F10) — deleting it from one twin and not the other creates a divergence the next maintainer has to re-derive. Deleting the method would also orphan the alias entirely, discarding the only remaining record of intake-agent's haiku tier. Task 5 Step 6 adds a comment to `litellm-config.yaml` saying it has no caller today, so nobody reads it as wired up.
- **`feedback-condense` (`litellm-config.yaml:127`, sonnet-5) — KEEP, unused and documented; do not wire it in this phase.** The condense step (F2, prompt key `"feedback_condense"` at `feedback.py:99`) is the highest-volume sonnet call in the worker — one per topic per interview — and this alias exists so it can be re-tiered independently later. Wiring it now would require a third method or a per-call alias override on the client, breaking the two-method surface the twin files share, for zero behavioural gain (`feedback-condense` and `feedback-sonnet` resolve to the same model today). Task 7 Step 3 adds a comment naming `src/services/feedback.py:99` as the workload it is reserved for and stating that pointing F2 at it is a one-line follow-up. **Do not delete it** — deleting a tier record is the thing the config header warns against.

---

## Everywhere a degraded reply lands on a default that reads as a real answer

CHECKPOINT fact #3: *"a degraded LLM reply (truncated tool call → `arguments={}`) lands on a default that reads as a REAL answer. Found three times in phase 2 … When migrating any call site, ask what an empty `arguments` dict does to it."* Phase 3 found two more. **This is the fifth and sixth.**

Neither worker uses tools, so there is no `arguments={}`. The non-tool equivalent is a **blank or near-blank completion**: the gateway answers 200 with `choices[0].message.content` of `""` or `None`. Today's Anthropic-shaped read `resp_json["content"][0]["text"]` produces `""` the same way. Both parsers turn `""` into an exception (`parse_json_response` raises `ValueError` at `json_response.py:46`; `_parse_rounds_json` raises `JSONDecodeError` at `pipeline.py:170`), so the question at every site is **who catches that exception, and what do they put in its place.**

| # | Site | What an empty reply produces today | Severity | Guard | Task/Step |
|---|---|---|---|---|---|
| **F1** | `feedback.py:54` `parse_json_response(extract_response)` | Raises, **uncaught**, propagates through `orchestrator.process_complete` to the handler. But a reply that is *valid JSON without the key* → `extract_result.get("extracted_bullets", {})` → `{}` → **zero bullets, no error, an empty scorecard presented as a completed run.** | **MEDIUM** | require `"extracted_bullets"` in the parsed dict | 3, Step 2 |
| **F2** | `feedback.py:105-121` | `except Exception:` at `:117` swallows everything → `condensed_results[topic_id] = {"raw_bullets": [...], "condensed": []}`. **Not logged at all.** An empty `condensed` list is indistinguishable from "the model condensed this topic to nothing", and that topic silently vanishes from the recruiter's scorecard. | **DANGEROUS** | require `"condensed_feedback"`; log `condense_llm_failed`; never swallow `EmptyLLMReply` | 3, Step 3 |
| **F3** | `interview.py:108` | Raises, **uncaught**, propagates. | SAFE (loud) | none needed; pin with a test | 3, Step 8 |
| **F4** | `interview.py:134-141`, caught at `:60-61` | `except Exception: detection_info["auto_detected"] = True`. Candidate and interviewer stay `"Unknown"` — visible — but `auto_detected: True` **asserts a detection that never happened**, and nothing is logged. | **MEDIUM** | log `participant_detection_failed`; set `auto_detected: False` when nothing was detected | 3, Step 4 |
| **F5** | `interview.py:150-157`, same handler | identical to F4 | **MEDIUM** | same | 3, Step 4 |
| **F6** | `judge.py:75-81` | `except Exception: choice = "feedback"` → falls to the `else` at `:95` → **`evidence_status="supported"`** on a `JudgedFeedbackItem` shown to a hiring panel. `reasoning` says "Judgment failed, defaulting to original feedback", but `evidence_status` is the field the scorecard badges. **Not logged.** This is phase 2's fabricated `likely_authentic` verdict, verbatim, in a different service. | **DANGEROUS** | require `"choice"`; on failure re-raise so `judge_all`'s `asyncio.gather(return_exceptions=True)` at `:26` drops the item and logs `judge_failed` at `:31` — the path that already exists and already works | 3, Step 5 |
| **F7** | `summary.py:97-106` | `except Exception as e:` **logs** `question_summary_llm_failed`, then `summary = item.feedback`. Falling back to the raw feedback is defensible, but it is rendered as a generated summary. | LOW | keep the fallback; require `"summary"`; add the alias to the log line | 3, Step 6 |
| **F8** | `summary.py:160-168` | `except Exception as e:` logs `round_summary_llm_failed`, returns `("Unable to generate summary", "")`. The string names itself. | SAFE | none needed; pin with a test | 3, Step 8 |
| **F9** | `evidence.py:153-161` | `except Exception:` → `{"feedback_evidence": [], "antifeedback_evidence": [], "reasoning": "Evidence extraction failed"}`, returned as a **normal `EnrichedFeedbackItem`**. It does not raise, so the `gather(return_exceptions=True)` logger at `evidence.py:90` never sees it. That item then flows into F6, which judges it on empty evidence and stamps `evidence_status="supported"` with an **empty evidence list** on the scorecard. **Two silent defaults compounding.** | **DANGEROUS** | require `"feedback_evidence"`; on failure **raise**, so the existing `evidence_extraction_failed` logger fires and the item is dropped rather than fabricated | 3, Step 7 |
| **F10** | `verdict.py:42-56` | `except Exception as e:` logs `verdict_extraction_failed`, then **returns `VerdictResult(verdicts=[], primary_rating="maybe")`**. `"maybe"` is a real hiring rating in this system (`summary.py:176,208,210` produce it deliberately). The caller cannot distinguish "the interviewer said maybe" from "the LLM returned nothing". | **DANGEROUS** | require `"verdicts"`; return `primary_rating=None` (or an explicit `"unknown"`) on failure and make the caller handle it — never a valid rating value | 3, Step 8 |
| **I1** | `pipeline.py:100` → `_parse_rounds_json` (`:162-183`) | `json.loads("")` raises → propagates → `handler.process_intake_v2` `except Exception` at `:74` → `mark_session_failed(f"{type(e).__name__}: {e}")` → returns `"failed"`. The failure is persisted and surfaced. | **SAFE** | none needed at the site; pin with a test | 6, Step 2 |
| **I2** | `pipeline.py:120` → `_parse_round_details_json` (`:185-201`) | identical path; additionally raises on a valid-JSON reply missing `guidelines` or `feedback_questions`. | **SAFE** | none needed at the site; pin with a test | 6, Step 2 |

**The two-layer guard this plan installs.** Neither layer alone is sufficient, and the F9 → F6 compounding is why.

1. **Client layer (Task 2 / Task 5), one choke point per worker.** `_read_content` raises `EmptyLLMReply` when `choices` is empty, when `message.content` is `None`, or when it is blank after `.strip()`. The client **never returns `""`**. This is the analogue of `llm_core._first_choice` (`llm-core/llm_core/client.py:50-60`) and it converts the entire class of "gateway answered 200 with nothing" from a silent default into a named, catchable exception carrying the alias and `finish_reason`.
2. **Site layer (Task 3 / Task 6), one guard per vulnerable site.** For a tool call the phase-2/3 rule is *"key the guard on the tool schema's required property."* With no tools, the equivalent is the **key the site reads out of the parsed dict** — `extracted_bullets`, `condensed_feedback`, `choice`, `summary`, `feedback_evidence`, `verdicts`. A parsed reply missing its required key is not a partial answer; it is a different answer. Each guard raises or logs-and-fails rather than falling through to `.get(key, <plausible default>)`.

**`EmptyLLMReply` must never be swallowed into a plausible default.** Every `except Exception` listed above is narrowed or re-raised in Task 3.

---

## Test inventory and suite arithmetic

**Rewritten or added by this plan (0 rewritten, 5 new files):**

| File | Tests at HEAD | What it encodes | Task |
|---|---|---|---|
| `workers/feedback-agent/tests/test_llm_client.py` | **new** | wire shape, alias routing, tier preservation, `EmptyLLMReply`, no-tools pin | 2 |
| `workers/feedback-agent/tests/test_degraded_reply_guards.py` | **new** | one test per vulnerable site F1-F10 | 3 |
| `workers/intake-agent/tests/test_llm_client.py` | **new** | same, for `intake-agent-*` | 5 |
| `workers/intake-agent/tests/test_degraded_reply.py` | **new** | I1/I2 fail loudly and reach `mark_session_failed` | 6 |
| `workers/intake-agent/tests/test_handler_warm.py` | 3 | `patch("production.handler.AnthropicClient")` at `:53`, `:76` — **2 string edits only** | 5 |
| `workers/feedback-agent/tests/test_orchestrator_holistic.py` | 1 | imports `FeedbackOrchestrator`; monkeypatches `process_complete`, so it never reaches the client — **no edit needed** | — |
| `workers/intake-agent/tests/test_pipeline.py`, `test_screenable_flag.py` | 6, 5 | `anthropic.call_sonnet.side_effect` on an `AsyncMock` — method names preserved, **no edit needed** | — |

**Deliberately untouched:** `workers/feedback-agent/tests/test_fixture_schema.py`, `test_models_new_fields.py`, `test_normalize_fixture.py`, `test_result_transformer.py`, `test_runner.py`, `test_supabase_feedback_source.py` — none reference the client, the wire shape, `httpx`, or any LLM-calling service. Confirmed by grep at HEAD.

### Suite arithmetic — every task, end to end

| after task | feedback-agent | intake-agent | note |
|---|---|---|---|
| baseline (measured in Task 1) | **34 (expected)** | **14 (expected)** | Task 1 pastes the real numbers; every row below is relative to those |
| 1 | 34 | 14 | test images + Makefile targets only, no test changes |
| 2 | 34 + 12 = **46** | 14 | `test_llm_client.py` |
| 3 | 46 + 14 = **60** | 14 | `test_degraded_reply_guards.py`, one test per site F1-F10 plus 4 client-layer interactions |
| 4 | 60 | 14 | `src/api/server.py` has no tests |
| 5 | 60 | 14 + 10 = **24** | `test_llm_client.py`; `test_handler_warm.py` edited, count unchanged |
| 6 | 60 | 24 + 6 = **30** | `test_degraded_reply.py` |
| 7 | 60 | 30 | wiring only |

Final: **feedback-agent 60, intake-agent 30.** Backend unchanged at **2185 passed / 5 skipped**.

---

## File Structure

| Path | Change | Task |
|---|---|---|
| `workers/feedback-agent/Dockerfile.test` | **new** | 1 |
| `workers/intake-agent/Dockerfile.test` | **new** | 1 |
| `Makefile` | **new targets** `test-feedback-agent`, `test-intake-agent` | 1 |
| `workers/feedback-agent/src/clients/llm.py` | **new** — replaces `anthropic.py` | 2 |
| `workers/feedback-agent/src/clients/anthropic.py` | **deleted** | 2 |
| `workers/feedback-agent/src/clients/__init__.py` | export rename | 2 |
| `workers/feedback-agent/src/config/settings.py` | gateway settings replace the Anthropic ones | 2 |
| `workers/feedback-agent/src/services/{feedback,interview,judge,summary,evidence,verdict,orchestrator}.py` | import + type + constructor rename | 2 |
| `workers/feedback-agent/local/api/routes/topics.py` | import rename | 2 |
| `workers/feedback-agent/tests/test_llm_client.py` | **new** | 2 |
| `workers/feedback-agent/src/services/{feedback,interview,judge,summary,evidence,verdict}.py` | degraded-reply guards | 3 |
| `workers/feedback-agent/tests/test_degraded_reply_guards.py` | **new** | 3 |
| `workers/feedback-agent/src/api/server.py`, `workers/feedback-agent/src/api/__init__.py`, `workers/feedback-agent/src/ui/` | **deleted** | 4 |
| `workers/intake-agent/src/clients/llm.py` | **new** — replaces `anthropic.py` | 5 |
| `workers/intake-agent/src/clients/anthropic.py` | **deleted** | 5 |
| `workers/intake-agent/src/clients/__init__.py`, `src/pipeline.py`, `production/handler.py` | rename | 5 |
| `workers/intake-agent/src/config/settings.py` | gateway settings | 5 |
| `workers/intake-agent/tests/test_handler_warm.py` | 2 patch-string edits | 5 |
| `workers/intake-agent/tests/test_llm_client.py` | **new** | 5 |
| `workers/intake-agent/tests/test_degraded_reply.py` | **new** | 6 |
| `docker-compose.yml` | `depends_on: litellm` (healthy) ×2 | 7 |
| `.env.example` | worker gateway vars documented | 7 |
| `litellm-config.yaml` | comments on the two orphan aliases + the four worker aliases | 7 |

---

### Task 1: Give both workers a test gate

Nothing else in this plan may start. Phase 5 rewrites ten call sites that **no test has ever executed** (verified: `tests/test_orchestrator_holistic.py:59-60` monkeypatches away the only method that reaches the client). An unverifiable rewrite of ten call sites is not shippable, and there is currently no way to verify it: `Makefile` has no worker target, `.github/workflows/gate.yml` has no test job (blocker B13), and feedback-agent's suite **cannot run on a bare host** because `tests/test_orchestrator_holistic.py:17` imports `src.services.orchestrator`, which pulls `EmbeddingService` → `sentence-transformers` → `torch`.

This task adds nothing but the ability to measure, and it establishes the two baselines every later task compares against.

**Files:**
- Create: `workers/feedback-agent/Dockerfile.test`
- Create: `workers/intake-agent/Dockerfile.test`
- Modify: `Makefile`

**Interfaces:** none — no source code changes.

- [ ] **Step 1: Create `workers/feedback-agent/Dockerfile.test`**

Mirrors `backend/Dockerfile.test` (which the `make test` target builds with the repo root as context). Two differences from the runtime `Dockerfile`: it installs `requirements-dev.txt` (which pulls `pytest`, `pytest-asyncio`, and `-r requirements.txt`), and it copies `tests/`, `local/`, `scripts/` and `evals/` which the runtime image deliberately omits.

```dockerfile
# Test image for the feedback worker (tag: openrecruiting-feedback-agent-test).
#
#   docker build -f workers/feedback-agent/Dockerfile.test -t openrecruiting-feedback-agent-test .
#   docker run --rm -v "$PWD/workers/feedback-agent:/app" -w /app \
#     openrecruiting-feedback-agent-test python -m pytest -q
#
# Why a container rather than a host venv: tests/test_orchestrator_holistic.py
# imports src.services.orchestrator, which reaches EmbeddingService ->
# sentence-transformers -> torch. The suite is not runnable on a bare host.
#
# Why `python -m pytest` and not `pytest`: workers/feedback-agent/tests/ has no
# __init__.py and there is no conftest.py anywhere in this worker, so pytest puts
# tests/ on sys.path rather than the worker root. `from src.services...` resolves
# only because `python -m` also puts CWD on sys.path. A bare `pytest` collects
# nothing but ModuleNotFoundError.
FROM python:3.11-slim

WORKDIR /app

# requirements-dev.txt starts with `-r requirements.txt`, so this installs both.
COPY workers/feedback-agent/requirements.txt workers/feedback-agent/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY workers/feedback-agent/ /app/
```

- [ ] **Step 2: Create `workers/intake-agent/Dockerfile.test`**

`workers/intake-agent/` has **no `requirements-dev.txt` and no `requirements.txt`** — verified, only `production/requirements.txt` (4 lines: httpx, pydantic-settings, structlog, python-dotenv). Install the test tools explicitly rather than creating a dev requirements file this worker has never had.

```dockerfile
# Test image for the intake worker (tag: openrecruiting-intake-agent-test).
#
#   docker build -f workers/intake-agent/Dockerfile.test -t openrecruiting-intake-agent-test .
#   docker run --rm -v "$PWD/workers/intake-agent:/app" -w /app \
#     openrecruiting-intake-agent-test python -m pytest -q
#
# This worker has no requirements.txt or requirements-dev.txt — production/
# requirements.txt is the only pin file it has ever had. pytest and pytest-asyncio
# are installed directly here rather than by inventing a dev pin file, so the
# runtime dependency set stays exactly what the Lambda ships.
FROM python:3.11-slim

WORKDIR /app

COPY workers/intake-agent/production/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "pytest>=8.0" "pytest-asyncio>=0.23"

COPY workers/intake-agent/ /app/
```

- [ ] **Step 3: Add the two Makefile targets**

Insert after `test-cortex` in `Makefile`, matching its two-line build-then-run shape. Note both images build with the **repo root** as context (the trailing `.`), matching `make test`.

```makefile
# Neither worker suite runs anywhere else: gate.yml has no test job and these two
# had no Makefile target, so every regression in them has been invisible (recon
# blocker B13). feedback-agent's suite additionally cannot run on a bare host —
# it imports sentence-transformers via src.services.orchestrator.
test-feedback-agent:  ## Run the feedback worker suite (Python 3.11 in Docker)
	docker build -f workers/feedback-agent/Dockerfile.test -t openrecruiting-feedback-agent-test .
	docker run --rm -v "$(PWD)/workers/feedback-agent:/app" -w /app openrecruiting-feedback-agent-test python -m pytest -q

test-intake-agent:    ## Run the intake worker suite (Python 3.11 in Docker)
	docker build -f workers/intake-agent/Dockerfile.test -t openrecruiting-intake-agent-test .
	docker run --rm -v "$(PWD)/workers/intake-agent:/app" -w /app openrecruiting-intake-agent-test python -m pytest -q
```

- [ ] **Step 4: Measure and record both baselines**

Run:
```
make test-feedback-agent
make test-intake-agent
```

Expected, from a static count of `def test_` at HEAD (no `parametrize` in either suite): **feedback-agent 34 passed**, **intake-agent 14 passed**.

**These are predictions, not results.** Paste the actual `pytest -q` summary line for each into the commit message and into `.superpowers/sdd/CHECKPOINT.md`. If either differs from the prediction, **stop and reconcile before Task 2** — a mismatch means either an import error is being collected as a skip, or the static count missed something, and every arithmetic row in this plan is then wrong.

- [ ] **Step 5: Self-review and commit**

Run `git diff --cached` and confirm: three files, no source change, no secret, no `.env`.

```
git add workers/feedback-agent/Dockerfile.test workers/intake-agent/Dockerfile.test Makefile
git commit -m "test(workers): give feedback-agent and intake-agent a runnable test gate

Neither suite has ever run in CI or from the Makefile (recon B13), and
feedback-agent's cannot run on a bare host at all — test_orchestrator_holistic
imports src.services.orchestrator, which reaches sentence-transformers via
EmbeddingService. Phase 5 rewrites ten call sites that no test has executed;
this is the ability to know whether that worked.

Baselines: feedback-agent <N> passed, intake-agent <M> passed."
```

---

### Task 2: feedback-agent — repoint the client at the gateway

Rewrites the client and updates its eight consumers in one commit. Behaviour at every call site is unchanged except the wire and the empty-reply guard; the degraded-reply *policy* changes are Task 3, deliberately separated so a reviewer can read the wire change and the behaviour change apart.

**Why the module and class are renamed.** `AnthropicClient` pointing at a provider-agnostic gateway is exactly the stale name this migration exists to remove, and it is free here: **no feedback-agent test references the class** (verified — the only test-side mention of any LLM module is an import of `FeedbackOrchestrator`). The rename is a mechanical eight-file edit and it makes a future reader unable to mistake this for a provider client.

**Files:**
- Create: `workers/feedback-agent/src/clients/llm.py`
- Delete: `workers/feedback-agent/src/clients/anthropic.py`
- Modify: `workers/feedback-agent/src/clients/__init__.py`, `src/config/settings.py`, `src/services/{feedback,interview,judge,summary,evidence,verdict,orchestrator}.py`, `local/api/routes/topics.py`
- Create: `workers/feedback-agent/tests/test_llm_client.py`

**Interfaces:**
- Produces: `LLMGatewayClient` with `async call(prompt, model: Literal["haiku","sonnet"]="sonnet", max_tokens=4096) -> str`, `async call_haiku(prompt, max_tokens=1024) -> str`, `async call_sonnet(prompt, max_tokens=4096) -> str`, `async close()`, `__aenter__`/`__aexit__`. Raises `EmptyLLMReply` (a subclass of `ValueError`) and `httpx.HTTPStatusError`.
- Consumes: `Settings.llm_gateway_url`, `.litellm_master_key`, `.llm_request_timeout`, `.llm_alias_haiku`, `.llm_alias_sonnet`.

- [ ] **Step 1: Write the failing test**

Create `workers/feedback-agent/tests/test_llm_client.py`:

```python
"""Tests for the gateway client. This worker had NO test touching its LLM client.

Verified at HEAD before this file existed: across all seven test files the only
reference to any LLM-calling module was `from src.services.orchestrator import
FeedbackOrchestrator` in test_orchestrator_holistic.py, and that test
monkeypatches away `process_complete` — the one method that reaches the client.
Not a single line of src/clients/ had ever been executed by a test.

What is pinned here, and why each one is a silent-failure class rather than a
style preference:

* the ALIAS, not a model id, goes on the wire — a model id would bypass the
  gateway's whole purpose and would 400 or, worse, resolve to a default;
* the TIER routing (haiku methods -> feedback-haiku, sonnet -> feedback-sonnet).
  litellm-config.yaml's header calls tier "part of the contract"; a swap here
  silently re-prices and re-times three haiku workloads;
* an empty completion RAISES rather than returning "". Six call sites in this
  worker catch broad exceptions and substitute a plausible default (see
  test_degraded_reply_guards.py), so a client that returns "" hands them the
  ingredients for a fabricated answer;
* NO `tools` key is ever sent. Neither worker uses tools today; this test fails
  the moment one does, which is when the OpenAI function-shape question becomes
  real and this plan's "no schema conversion needed" claim stops holding.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.clients.llm import EmptyLLMReply, LLMGatewayClient


def _response(content: str | None, *, finish_reason: str = "stop") -> MagicMock:
    """A minimal OpenAI-shaped 200 from the gateway."""
    resp = MagicMock(spec=httpx.Response)
    resp.raise_for_status = MagicMock(return_value=None)
    resp.json = MagicMock(
        return_value={
            "id": "chatcmpl-x",
            "model": "anthropic/claude-sonnet-5",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        }
    )
    return resp


def _client_with(response: MagicMock) -> tuple[LLMGatewayClient, AsyncMock]:
    client = LLMGatewayClient()
    transport = AsyncMock()
    transport.post = AsyncMock(return_value=response)
    transport.is_closed = False
    client._client = transport
    return client, transport


@pytest.mark.asyncio
async def test_posts_to_the_gateway_and_never_to_a_provider():
    client, transport = _client_with(_response("hello"))
    await client.call_sonnet("prompt")

    url = transport.post.call_args[0][0]
    assert url.endswith("/v1/chat/completions")
    assert "anthropic.com" not in url
    assert "litellm" in url or "localhost" in url or "127.0.0.1" in url


@pytest.mark.asyncio
async def test_call_sonnet_sends_the_feedback_sonnet_alias():
    client, transport = _client_with(_response("ok"))
    await client.call_sonnet("prompt")
    assert transport.post.call_args.kwargs["json"]["model"] == "feedback-sonnet"


@pytest.mark.asyncio
async def test_call_haiku_sends_the_feedback_haiku_alias():
    """Tier preservation. F4, F5 and F10 run on haiku today; litellm-config.yaml
    maps feedback-haiku to the byte-identical claude-haiku-4-5-20251001."""
    client, transport = _client_with(_response("ok"))
    await client.call_haiku("prompt")
    assert transport.post.call_args.kwargs["json"]["model"] == "feedback-haiku"


@pytest.mark.asyncio
async def test_no_provider_model_id_ever_reaches_the_wire():
    client, transport = _client_with(_response("ok"))
    await client.call_sonnet("prompt")
    body = json.dumps(transport.post.call_args.kwargs["json"])
    assert "claude-" not in body
    assert "anthropic" not in body.lower()


@pytest.mark.asyncio
async def test_no_tools_key_is_ever_sent():
    """Pins this plan's central claim: neither worker uses tools, so no Anthropic
    input_schema -> OpenAI function-shape conversion exists to get wrong. If this
    fails, that claim has stopped being true and the tool-spec migration rules in
    CHECKPOINT fact #7 apply."""
    client, transport = _client_with(_response("ok"))
    await client.call_sonnet("prompt")
    payload = transport.post.call_args.kwargs["json"]
    assert "tools" not in payload
    assert "tool_choice" not in payload
    assert set(payload) == {"model", "max_tokens", "temperature", "messages"}


@pytest.mark.asyncio
async def test_authorization_is_a_bearer_header_not_an_api_key_header():
    client = LLMGatewayClient()
    transport = await client._get_client()
    try:
        assert "x-api-key" not in {k.lower() for k in transport.headers}
        assert transport.headers.get("authorization", "").startswith("Bearer ")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_reads_the_openai_content_path():
    client, _ = _client_with(_response("the answer"))
    assert await client.call_sonnet("prompt") == "the answer"


@pytest.mark.asyncio
async def test_an_empty_completion_raises_rather_than_returning_blank():
    client, _ = _client_with(_response("", finish_reason="length"))
    with pytest.raises(EmptyLLMReply) as exc:
        await client.call_sonnet("prompt")
    assert "feedback-sonnet" in str(exc.value)
    assert "length" in str(exc.value)


@pytest.mark.asyncio
async def test_a_null_completion_raises():
    """A content-filtered or tool-only choice carries content=None, not ""."""
    client, _ = _client_with(_response(None, finish_reason="content_filter"))
    with pytest.raises(EmptyLLMReply):
        await client.call_sonnet("prompt")


@pytest.mark.asyncio
async def test_a_whitespace_only_completion_raises():
    client, _ = _client_with(_response("   \n  "))
    with pytest.raises(EmptyLLMReply):
        await client.call_sonnet("prompt")


@pytest.mark.asyncio
async def test_an_empty_choices_list_raises():
    """A gateway that answers 200 with an error envelope. Without this the read
    is an IndexError straight through every `except Exception` in this worker."""
    resp = MagicMock(spec=httpx.Response)
    resp.raise_for_status = MagicMock(return_value=None)
    resp.json = MagicMock(return_value={"choices": []})
    client, _ = _client_with(resp)
    with pytest.raises(EmptyLLMReply):
        await client.call_sonnet("prompt")


@pytest.mark.asyncio
async def test_a_non_retryable_status_propagates():
    """The hand-rolled 429/5xx backoff is deleted — litellm owns retries
    (litellm-config.yaml:199, num_retries: 2). A 4xx must surface immediately."""
    resp = MagicMock(spec=httpx.Response)
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("400", request=MagicMock(), response=MagicMock(status_code=400))
    )
    client, _ = _client_with(resp)
    with pytest.raises(httpx.HTTPStatusError):
        await client.call_sonnet("prompt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test-feedback-agent`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'src.clients.llm'`.

- [ ] **Step 3: Replace the Anthropic settings with gateway settings**

In `workers/feedback-agent/src/config/settings.py`, replace lines 10-14:

```python
    anthropic_api_key: str = ""
    anthropic_model_haiku: str = "claude-haiku-4-5-20251001"
    anthropic_model_sonnet: str = "claude-sonnet-4-6"
    anthropic_timeout: int = 120
    anthropic_max_retries: int = 3
```

with:

```python
    # Text generation egresses through the LiteLLM gateway, never a provider.
    # The default matches docker-compose's service name so a container needs no
    # env var; a host process must export LLM_GATEWAY_URL=http://localhost:4000
    # (the live .env does not define it — recon B14).
    llm_gateway_url: str = "http://litellm:4000"
    litellm_master_key: str = ""

    # Deliberately NOT named llm_timeout_seconds. That env name is llm-core's
    # knob and .env.example:150 already documents it as 60; reusing it here would
    # silently halve this worker's request budget the first time someone sets it.
    # 120 preserves the anthropic_timeout this replaces.
    llm_request_timeout: float = 120

    # Gateway ALIASES, not model ids. litellm-config.yaml resolves them, and its
    # header makes tier part of the contract: feedback-haiku is
    # claude-haiku-4-5-20251001 (byte-identical to the old default) and
    # feedback-sonnet is claude-sonnet-5 (phase 1's documented 4-6 -> 5 bump).
    llm_alias_haiku: str = "feedback-haiku"
    llm_alias_sonnet: str = "feedback-sonnet"
```

`anthropic_max_retries` goes with them — see Step 4.

- [ ] **Step 4: Write `src/clients/llm.py`**

```python
"""The only module in this worker that speaks to an LLM endpoint.

Talks OpenAI-shaped HTTP to the LiteLLM gateway. Model names are aliases the
gateway resolves to real providers, so provider choice is configuration.

This is a hand-rolled httpx client rather than the shared `llm-core` package, on
purpose. workers/feedback-agent/deploy/ecr-push.sh:25,53 builds the Lambda image
with workers/feedback-agent/ as its context, so production/Dockerfile physically
cannot COPY llm-core from the repo root (recon blocker B5). Adopting llm-core
would mean rewriting that build path inside this phase for a deploy path nobody
has confirmed is live — and it would buy nothing: this worker sends no tools,
never streams, and every request is one user message in, one string out. What was
actually needed was a URL, a Bearer header, and choices[0].message.content.

Two things were DELETED rather than ported:

1. The 429/5xx exponential backoff loop. litellm owns retries now
   (litellm-config.yaml:199, `num_retries: 2`), and duplicating them multiplied
   the effective retry count. Connection failures to the gateway itself now
   surface immediately, which is correct: docker-compose gates this service on
   litellm being healthy.
2. call_haiku_sync / call_sonnet_sync. Zero callers repo-wide (verified by grep
   across every .py/.md/.txt), and each opened its own httpx.Client straight at
   api.anthropic.com — two live provider-egress paths in a repo whose whole point
   is a single one.
"""

import time

import httpx

from src.config import get_settings
from src.logging import get_logger

logger = get_logger(__name__)


class EmptyLLMReply(ValueError):
    """The gateway answered 200 but carried no usable completion.

    A ValueError subclass so the parse-failure handlers already scattered through
    src/services/ see a familiar type — but a DISTINCT type, because those
    handlers must stop treating it as "the model said something I could not
    parse" and start treating it as "the model said nothing". Six call sites in
    this worker turn a parse failure into a plausible default (a "supported"
    evidence status, a "maybe" hiring rating, an empty condensed-feedback list),
    which is CHECKPOINT fact #3's bug shape. Raising a named type is what lets
    Task 3's guards refuse to swallow it.
    """


class LLMGatewayClient:
    def __init__(self):
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None

    @property
    def url(self) -> str:
        return f"{self.settings.llm_gateway_url.rstrip('/')}/v1/chat/completions"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.llm_request_timeout),
                headers={
                    "authorization": f"Bearer {self.settings.litellm_master_key}",
                    "content-type": "application/json",
                },
            )
        return self._client

    def _alias(self, model: str) -> str:
        return (
            self.settings.llm_alias_haiku
            if model == "haiku"
            else self.settings.llm_alias_sonnet
        )

    @staticmethod
    def _read_content(resp_json: dict, alias: str) -> str:
        """Pull choices[0].message.content, or raise. Never returns "".

        The Anthropic-era read was resp_json["content"][0]["text"], which threw a
        bare KeyError/IndexError on a degraded reply — a shape error travelling
        through handlers written for parse errors. This names the failure and
        carries the alias and finish_reason, which is what makes a truncation
        ("length") distinguishable from a filter ("content_filter") in a log.
        """
        choices = resp_json.get("choices") or []
        if not choices:
            raise EmptyLLMReply(f"{alias}: gateway returned no choices")

        choice = choices[0] or {}
        text = (choice.get("message") or {}).get("content")
        if text is None or not text.strip():
            raise EmptyLLMReply(
                f"{alias}: gateway returned an empty completion "
                f"(finish_reason={choice.get('finish_reason')!r})"
            )
        return text

    async def call(
        self,
        prompt: str,
        model: str = "sonnet",
        max_tokens: int = 4096,
    ) -> str:
        client = await self._get_client()
        alias = self._alias(model)

        payload = {
            "model": alias,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }

        logger.info("llm_request", alias=alias, prompt_len=len(prompt))
        llm_start = time.monotonic()

        response = await client.post(self.url, json=payload)
        response.raise_for_status()
        resp_json = response.json()

        result = self._read_content(resp_json, alias)

        # OpenAI usage keys, NOT Anthropic's input_tokens/output_tokens. Reading
        # the old names against the new envelope would log 0/0 forever and lose
        # this worker's only cost signal without anything failing.
        usage = resp_json.get("usage") or {}
        logger.info(
            "llm_response",
            alias=alias,
            resolved_model=resp_json.get("model"),
            response_len=len(result),
            duration_ms=int((time.monotonic() - llm_start) * 1000),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        return result

    async def call_haiku(self, prompt: str, max_tokens: int = 1024) -> str:
        return await self.call(prompt, model="haiku", max_tokens=max_tokens)

    async def call_sonnet(self, prompt: str, max_tokens: int = 4096) -> str:
        return await self.call(prompt, model="sonnet", max_tokens=max_tokens)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
```

**`call_haiku`'s `max_tokens` default stays 1024 and `call_sonnet`'s stays 4096** — verified against `src/clients/anthropic.py:115,118`. Do not "harmonise" them with intake-agent's 4096/8192; those are different workloads and changing a token budget is a behaviour change this phase is not making.

- [ ] **Step 5: Delete the old client and update its eight consumers**

```
git rm workers/feedback-agent/src/clients/anthropic.py
```

`src/clients/__init__.py` — before:
```python
from .anthropic import AnthropicClient
...
__all__ = ["AnthropicClient", "SupabaseClient", "get_supabase_client"]
```
after:
```python
from .llm import EmptyLLMReply, LLMGatewayClient
...
__all__ = ["EmptyLLMReply", "LLMGatewayClient", "SupabaseClient", "get_supabase_client"]
```

Then, in each file below, replace `from src.clients.anthropic import AnthropicClient` with `from src.clients.llm import LLMGatewayClient`, and every `AnthropicClient` occurrence (type annotation or constructor) with `LLMGatewayClient`:

| File | `AnthropicClient` occurrences (verified at HEAD) |
|---|---|
| `src/services/feedback.py` | `:3` import, `:17` annotation, `:51` ctor, `:109` ctor |
| `src/services/interview.py` | `:4` import, `:32` annotation, `:105` ctor, `:123` annotation, `:137` ctor, `:153` ctor |
| `src/services/judge.py` | `:4` import, `:21` ctor, `:50` annotation |
| `src/services/summary.py` | `:3` import, `:23` ctor, `:41` ctor, `:77` annotation, `:122` annotation |
| `src/services/evidence.py` | `:3` import, `:70` ctor, `:136` annotation |
| `src/services/verdict.py` | `:3` import, `:29` annotation, `:46` ctor |
| `src/services/orchestrator.py` | `:3` import, `:47` ctor |
| `local/api/routes/topics.py` | `:6` import (unused beyond the import — check before keeping it) |

Verify completeness before moving on:
```
grep -rn 'AnthropicClient\|anthropic' --include='*.py' workers/feedback-agent/src workers/feedback-agent/local workers/feedback-agent/production workers/feedback-agent/integration
```
Expected: **only** `src/api/server.py` (Task 4 deletes it) and nothing else. If `src/config/settings.py` still matches, Step 3 was incomplete.

- [ ] **Step 6: Run test to verify it passes**

Run: `make test-feedback-agent`
Expected: **34 + 12 = 46 passed** (against Task 1's measured baseline). Paste the summary line.

- [ ] **Step 7: Self-review and commit**

`git diff --cached`. Confirm: no `api.anthropic.com` anywhere outside `src/api/server.py`; no `x-api-key`; no literal key; no `claude-` model id outside `litellm-config.yaml`.

```
git add -A workers/feedback-agent
git commit -m "feat(feedback-agent): repoint the LLM client at the gateway

Ten production call sites move from api.anthropic.com to the LiteLLM proxy with
an OpenAI-shaped payload. call_haiku -> feedback-haiku (byte-identical model id,
tier preserved), call_sonnet -> feedback-sonnet (sonnet-4-6 -> sonnet-5, phase
1's documented bump). Method names are unchanged so no call site's shape moves.

Deleted rather than ported: the 429/5xx backoff loop (litellm owns retries,
num_retries: 2) and call_haiku_sync/call_sonnet_sync, which had zero callers
repo-wide and each opened its own direct httpx.Client at api.anthropic.com.

Added: EmptyLLMReply. The client can no longer return \"\" — six call sites in
this worker turn a blank reply into a plausible default, and Task 3 fixes them.

Hand-rolled httpx rather than llm-core because production/Dockerfile builds with
workers/feedback-agent/ as its context (deploy/ecr-push.sh:25,53) and cannot see
llm-core, and because this worker sends no tools and never streams.

feedback-agent: <N> passed."
```

---

### Task 3: feedback-agent — the degraded-reply guards, one step per vulnerable site

Task 2 made a blank reply raise instead of returning `""`. This task stops six handlers from catching that and substituting an answer. **Each vulnerable site gets its own step.** The full analysis is in the degraded-reply table above; the severity ratings there are the priority order.

**Expect fixtures to break.** Six did in phase 3 the moment required-args guards landed. `workers/feedback-agent/evals/` and `tests/test_fixture_schema.py` / `test_normalize_fixture.py` carry recorded LLM payloads. **Fix the fixture, never weaken the guard.** If a fixture genuinely records a degraded production reply, say so in the commit — that is the guard finding the bug it exists for.

**Files:**
- Modify: `src/services/{feedback,interview,judge,summary,evidence,verdict}.py`
- Create: `workers/feedback-agent/tests/test_degraded_reply_guards.py`

**Interfaces:** unchanged, with one deliberate exception — `VerdictResult.primary_rating` becomes `str | None` (Step 8).

- [ ] **Step 1: Write the failing tests**

Create `workers/feedback-agent/tests/test_degraded_reply_guards.py`. One test per row of the degraded-reply table, each named for the site and asserting the *outcome a recruiter would see*, not the internal call. The shape for each:

```python
@pytest.mark.asyncio
async def test_f6_judge_does_not_fabricate_a_supported_verdict_from_an_empty_reply():
    """CHECKPOINT fact #3, fifth instance. judge.py:75-81 caught every exception
    and set choice="feedback", which falls to the else at :95 and stamps
    evidence_status="supported" on an item shown to a hiring panel. That is
    phase 2's fabricated likely_authentic verdict in a different service."""
    client = AsyncMock()
    client.call_sonnet.side_effect = EmptyLLMReply("feedback-sonnet: empty")
    ...
    results = await JudgeService().judge_all([item], RoleContext())
    assert results == []            # dropped by gather(return_exceptions=True)
    # and NOT: a JudgedFeedbackItem with evidence_status="supported"
```

Cover, at minimum: F1 missing-key, F2 empty-reply and missing-key, F4/F5 `auto_detected` honesty, F6 no fabricated `supported`, F7 fallback still logged, F9 raises rather than returning empty evidence, F10 no fabricated `"maybe"`, plus F3 and F8 pinned as already-safe so a future refactor cannot quietly add a swallowing handler.

- [ ] **Step 2: F1 — `feedback.py:54`, require `extracted_bullets`**

Before (`:54-55`):
```python
        extract_result = parse_json_response(extract_response)
        extracted_bullets = extract_result.get("extracted_bullets", {})
```
After:
```python
        extract_result = parse_json_response(extract_response)
        if "extracted_bullets" not in extract_result:
            raise ValueError(
                "feedback_extract reply is missing 'extracted_bullets'; "
                f"keys={sorted(extract_result)}"
            )
        extracted_bullets = extract_result["extracted_bullets"]
```
`.get(..., {})` turned a structurally wrong reply into "this interview produced no feedback", presented as a completed run. Log the key list, never the values — they carry candidate feedback.

- [ ] **Step 3: F2 — `feedback.py:105-121`, stop swallowing into `condensed: []`**

Before (`:117-121`):
```python
            except Exception:
                condensed_results[topic_id] = {
                    "raw_bullets": raw_bullet_strings,
                    "condensed": [],
                }
```
After: require `"condensed_feedback"` in the parsed result, log `condense_failed` with `topic_id`, `alias` and `error`, and **let `EmptyLLMReply` propagate** rather than degrading. The bare `except Exception` here is the only handler in this file and it is silent; a topic that fails to condense currently disappears from the scorecard with no trace anywhere.

- [ ] **Step 4: F4 and F5 — `interview.py:48-62`, stop asserting a detection that did not happen**

Before (`:60-61`):
```python
            except Exception:
                detection_info["auto_detected"] = True
```
After: log `participant_detection_failed` with the error, and set `auto_detected` to **`False`** — nothing was detected. `candidate` and `interviewer` already stay `"Unknown"`, which is honest; the flag was the lie. Add the required-key guard (`"participants"`) inside `_detect_participants` at both `:140` and `:156` so a structurally wrong reply is distinguishable from a network failure.

- [ ] **Step 5: F6 — `judge.py:75-81`, never fabricate `evidence_status`**

Before:
```python
        try:
            response = await client.call_sonnet(prompt)
            result = parse_json_response(response)
            choice = result.get("choice", "feedback").lower()
            reasoning = result.get("reasoning", "")
        except Exception:
            choice = "feedback"
            reasoning = "Judgment failed, defaulting to original feedback"
```
After: require `"choice"` in `result`, and **remove the `except` entirely** so the exception propagates to `judge_all`'s `asyncio.gather(..., return_exceptions=True)` at `:26`, which already logs `judge_failed` at `:31` and drops the item at `:32`. That path exists, is tested by nothing today, and is exactly the right behaviour: a hiring panel sees one fewer judged item rather than one invented `"supported"`.

- [ ] **Step 6: F7 — `summary.py:97-106`, keep the fallback, name the reply**

The fallback to `item.feedback` is defensible and is already logged. Two edits: require `"summary"` in the parsed result rather than `.get("summary", item.feedback)`, so a structurally wrong reply is a logged failure rather than a silent passthrough; and add `alias` to the `question_summary_llm_failed` log line. Leave the fallback in place — dropping a question summary is worse than showing the raw feedback, and unlike F6 nothing downstream reads it as a verdict.

- [ ] **Step 7: F9 — `evidence.py:153-161`, raise instead of returning empty evidence**

Before:
```python
        except Exception:
            result = {
                "feedback_evidence": [],
                "antifeedback_evidence": [],
                "reasoning": "Evidence extraction failed",
            }
```
After: require `"feedback_evidence"` in `result`, and **delete the `except`**. `extract_evidence` already wraps these in `asyncio.gather(..., return_exceptions=True)` (`:85`) and logs `evidence_extraction_failed` at `:91-92`, dropping the item. This is the **worst site in the worker**: because the handler returns rather than raising, the gather-level logger never fires, and the empty-evidence item flows straight into F6, which judges it on nothing and stamps `evidence_status="supported"` with an empty evidence list on the scorecard. **Two silent defaults compounding into a confident, evidence-free verdict.** Fixing F9 and F6 in the same commit is deliberate.

- [ ] **Step 8: F10 — `verdict.py:42-56`, `"maybe"` is a real rating and must not be fabricated**

Before (`:51-56`):
```python
        except Exception as e:
            logger.error("verdict_extraction_failed", error=str(e))
            return VerdictResult(verdicts=[], primary_rating="maybe")
```
After: require `"verdicts"` in the parsed result; on failure keep the log line and return `primary_rating=None`. Widen the dataclass at `:22` to `primary_rating: str | None`, and update the caller — `orchestrator.py` passes it into `SummaryService.generate_summaries(verbal_verdict=...)`, which already handles a falsy value (`summary.py:88`, `:155` both do `verbal_verdict or "unknown"`). **Verify that claim by reading both lines before editing**; if any other consumer compares `primary_rating` to a rating literal, this step must also update it. `"maybe"` is produced deliberately by `_calculate_rating` (`summary.py:176, 208, 210`), so a fabricated one is indistinguishable from a real one.

Also in this step, pin the two already-safe sites: **F3** (`interview.py:108`, uncaught) and **F8** (`summary.py:160-168`, returns the self-describing `"Unable to generate summary"`). Add a test for each so a future refactor cannot quietly wrap them in a swallowing handler.

- [ ] **Step 9: Run test to verify it passes**

Run: `make test-feedback-agent`
Expected: **60 passed**. Paste the summary line.

If a pre-existing test or an `evals/` fixture fails: **read the failure before touching anything.** A fixture that trips a required-key guard is a fixture that records a reply the schema forbids. Fix the fixture. Record which ones in the commit body.

- [ ] **Step 10: Self-review and commit**

```
git add -A workers/feedback-agent
git commit -m "fix(feedback-agent): stop six call sites answering from an empty LLM reply

CHECKPOINT fact #3's bug shape, instances five and six. Before this, a blank
completion produced: a fabricated evidence_status=\"supported\" on a hiring
panel's scorecard (judge.py:80), a fabricated primary_rating=\"maybe\"
(verdict.py:55), an empty evidence list that then FED that verdict without ever
tripping the gather-level logger (evidence.py:157), a topic silently dropped from
the scorecard (feedback.py:117), and an auto_detected=True flag asserting a
participant detection that never ran (interview.py:61).

Each guard is keyed on the key the site actually reads, and EmptyLLMReply is
never swallowed. Where a drop-and-log path already existed (judge_all and
extract_evidence both use gather(return_exceptions=True)), the fix is to let the
exception reach it rather than to invent a new handler.

Fixtures corrected: <list, or 'none'>.

feedback-agent: <N> passed."
```

---

### Task 4: feedback-agent — delete the second Anthropic egress path

Blocker B6, settled. `src/api/server.py` carries its own `call_sonnet` (`:271`) using `requests` (`:14`, `:287`), a **hardcoded `"claude-sonnet-4-6"`** (`:282`), the Anthropic response read `response.json()["content"][0]["text"]` (`:294`), and its own credential lookup `os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")` (`:272`), across **9 call sites** (`:316, 405, 481, 505, 597, 637, 658, 790, 906`).

**Delete, do not migrate.** The evidence, all verified:

1. **It is a strict subset duplicate of `local/api/`.** Its six routes — `/map-topics` (`:337`), `/process-feedback` (`:450`), `/process-complete` (`:676`), `/extract-evidence` (`:822`), `/judge-feedback` (`:936`), `/health` (`:960`) — every one exists under `local/api/routes/`, which additionally serves `/rounds`, `/rounds/{id}` and `/rounds/{id}/process`. `local/api/` routes through `src/services/`, which Tasks 2 and 3 already migrated and guarded.
2. **Nothing runs it.** `workers/feedback-agent/app.py:22` imports `production.handler`. `workers/feedback-agent/docker-compose.yml:37` runs `streamlit run local/ui/round_tester.py`. Repo-wide, the only mentions of `src.api.server` are two Streamlit *error strings* (`src/ui/topic_mapper.py:97`, `local/ui/topic_mapper.py:98`).
3. **It cannot import in any shipped image.** `requests` is absent from both `requirements.txt` and `production/requirements.txt`; only `types-requests` appears, in `requirements-dev.txt`. Both the compose `Dockerfile:11` and `production/Dockerfile:4` install `production/requirements.txt`.
4. `src/ui/` is the same story: 4 files, each differing from its `local/ui/` twin by 6 diff lines (`API_URL` gained an `os.getenv`), with `local/ui/` additionally carrying `round_tester.py` — the one thing compose actually launches. Both directories landed in the same commit, `255c049`.

Migrating it would mean maintaining a second gateway client for a dead duplicate. Leaving it means leaving a hardcoded `claude-sonnet-4-6` and a second provider egress in a repo whose entire deliverable is a single one.

**Files:**
- Delete: `workers/feedback-agent/src/api/server.py`, `workers/feedback-agent/src/api/__init__.py`, `workers/feedback-agent/src/ui/` (4 files)

**Interfaces:** none removed that anything consumes — proven in Step 1.

- [ ] **Step 1: Prove nothing consumes either path**

```
grep -rn 'src\.api\|src/api\|src\.ui\|src/ui' --include='*.py' --include='*.sh' --include='*.yml' --include='*.yaml' --include='*.toml' --include='*.md' --include='*.txt' .
```
Expected: only the two Streamlit error strings named above. **If anything else appears, stop and re-plan this task** — the delete is only safe because nothing consumes it.

- [ ] **Step 2: Delete**

```
git rm -r workers/feedback-agent/src/api workers/feedback-agent/src/ui
```

- [ ] **Step 3: Fix the two stale error strings**

`local/ui/topic_mapper.py:98` reads ``st.error("Cannot connect to API server. Make sure it's running: `uvicorn src.api.server:app --reload`")``. That module is gone; point it at the app that actually exists: `uvicorn local.api.app:app --reload`. (`src/ui/topic_mapper.py:97` carried the same string and is deleted with its directory.)

- [ ] **Step 4: Prove the worker is clean**

```
grep -rn 'anthropic\|api\.anthropic\.com\|claude-' --include='*.py' workers/feedback-agent
```
Expected: **nothing**. This is the task's real acceptance criterion.

- [ ] **Step 5: Run test to verify it passes**

Run: `make test-feedback-agent`
Expected: **60 passed**, unchanged — `src/api/server.py` and `src/ui/` have no tests.

- [ ] **Step 6: Self-review and commit**

```
git add -A workers/feedback-agent
git commit -m "chore(feedback-agent): delete the second Anthropic egress path

src/api/server.py held its own call_sonnet over `requests` with a hardcoded
claude-sonnet-4-6 and nine call sites (recon B6, unmentioned by the spec). It is
a strict subset duplicate of local/api/ — all six of its routes exist there,
which also serves /rounds — nothing runs it (app.py mounts production.handler,
compose runs local/ui/round_tester.py), and it cannot import in any shipped image
because `requests` is in neither requirements file. src/ui/ is the same dead
duplicate of local/ui/, differing by six lines per file.

Migrating it would mean maintaining a second gateway client for a dead surface.

grep for anthropic|claude- across workers/feedback-agent now returns nothing.

feedback-agent: <N> passed."
```

---

### Task 5: intake-agent — repoint the client at the gateway

The same change on the twin file, plus two deletions specific to it. Independent of phases 3 and 4: **intake-agent does not import `intake_core`** (verified — the claim in `intake-core/README.md` that `intake-agent` is a consumer is stale).

**`cached_prefix` is deleted, not translated.** Declared at `:37`, consumed at `:53-56` and `:65`, forwarded at `:122-126` — and **never passed by any caller** (`src/pipeline.py`, `production/handler.py`, `local/api/`, `tests/` all checked). The block it builds is `system=[{"type":"text","text":...,"cache_control":{"type":"ephemeral"}}]`: the one Anthropic-wire-specific construct in either worker. Porting it to an OpenAI-shaped equivalent would mean inventing behaviour no caller exercises and no test covers, over LiteLLM's `cache_control` passthrough, which differs by provider. The spec's §Risks names prompt-caching loss only for `voice-agent`; **here nothing is lost, because the block was unreachable.**

**`call_haiku` is kept and migrated, not deleted.** Zero callers (B8, confirmed). See "The two orphan aliases" above for the full reasoning: post-repoint it is two lines naming a gateway alias, it preserves the file-for-file symmetry with `feedback-agent` where the identical method has three live callers, and deleting it would orphan `intake-agent-haiku` and discard the tier record.

**Files:**
- Create: `workers/intake-agent/src/clients/llm.py`
- Delete: `workers/intake-agent/src/clients/anthropic.py`
- Modify: `src/clients/__init__.py`, `src/config/settings.py`, `src/pipeline.py`, `production/handler.py`, `tests/test_handler_warm.py`
- Create: `workers/intake-agent/tests/test_llm_client.py`

**Interfaces:**
- Produces: `LLMGatewayClient` with `call_haiku(prompt, max_tokens=4096)` and `call_sonnet(prompt, max_tokens=8192)` — **note the different defaults from feedback-agent** (`src/clients/anthropic.py:122,125`, verified). Raises `EmptyLLMReply`.

- [ ] **Step 1: Write the failing test**

Create `workers/intake-agent/tests/test_llm_client.py` — the same 10-test shape as feedback-agent's, with `feedback-sonnet`/`feedback-haiku` replaced by `intake-agent-sonnet`/`intake-agent-haiku`, plus two tests specific to this worker:

```python
@pytest.mark.asyncio
async def test_the_default_token_budgets_are_unchanged():
    """anthropic.py:122,125 defaulted haiku to 4096 and sonnet to 8192 — DIFFERENT
    from feedback-agent's 1024/4096. Harmonising the twin files here would be a
    silent behaviour change to two live pipeline stages."""
    client, transport = _client_with(_response("ok"))
    await client.call_sonnet("p")
    assert transport.post.call_args.kwargs["json"]["max_tokens"] == 8192
    await client.call_haiku("p")
    assert transport.post.call_args.kwargs["json"]["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_no_cache_control_block_is_ever_sent():
    """cached_prefix built system=[{...,"cache_control":{"type":"ephemeral"}}] —
    the only Anthropic-wire-specific construct in either worker, and unreachable
    (never passed by any caller). Deleted rather than translated."""
    client, transport = _client_with(_response("ok"))
    await client.call_sonnet("p")
    body = json.dumps(transport.post.call_args.kwargs["json"])
    assert "cache_control" not in body
    assert "system" not in transport.post.call_args.kwargs["json"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test-intake-agent`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.clients.llm'`.

- [ ] **Step 3: Replace the Anthropic settings**

`workers/intake-agent/src/config/settings.py:10-14` → the same five gateway fields as Task 2 Step 3, with `llm_alias_haiku: str = "intake-agent-haiku"` and `llm_alias_sonnet: str = "intake-agent-sonnet"`. Same comment about `llm_request_timeout` not being named `llm_timeout_seconds`.

- [ ] **Step 4: Write `src/clients/llm.py`**

Copy Task 2 Step 4's module verbatim, with three differences, and say so in the docstring so the twin relationship is legible:
- `call_haiku` default `max_tokens=4096`; `call_sonnet` default `max_tokens=8192`.
- The docstring's "two things deleted" list becomes: the backoff loop, and `cached_prefix` (with the unreachability evidence).
- `EmptyLLMReply`'s docstring names this worker's actual behaviour: both parse sites already raise and `production/handler.py:74-85` already persists the failure via `mark_session_failed`, so `EmptyLLMReply` here is defence in depth that makes the *cause* legible in `process_error` rather than a `JSONDecodeError` on an empty string.

- [ ] **Step 5: Delete the old client and update its four consumers**

```
git rm workers/intake-agent/src/clients/anthropic.py
```

| File | occurrences (verified at HEAD) |
|---|---|
| `src/clients/__init__.py` | `:1` import, `:4` `__all__` |
| `src/pipeline.py` | `:12` import, `:74` annotation |
| `production/handler.py` | `:20` import, `:64` `async with AnthropicClient() as anthropic:` |
| `tests/test_handler_warm.py` | `:53`, `:76` — `patch("production.handler.AnthropicClient")` → `patch("production.handler.LLMGatewayClient")` |

The `self.anthropic` attribute on `IntakePipelineV2` (`:75`, read at `:100` and `:120`) may be renamed to `self.llm` **only if** `tests/test_pipeline.py` and `tests/test_screenable_flag.py` are checked first — they build `anthropic = AsyncMock()` and pass it positionally/by keyword. Preferred: **rename the attribute and the constructor kwarg, and update the three test call sites**, so no name in the worker still says "anthropic". Verify with the grep in Step 7.

- [ ] **Step 6: Comment the orphan alias**

In `litellm-config.yaml`, above `- model_name: intake-agent-haiku` (`:160`):

```yaml
  # HAIKU, mirroring workers/intake-agent Settings.anthropic_model_haiku before it
  # was flipped to this alias. NO CALLER TODAY: intake-agent's only production LLM
  # calls are src/pipeline.py:100 and :120, both sonnet. The client's call_haiku()
  # names this alias and is kept so the tier has a record and the file stays
  # symmetric with feedback-agent, where the identical method has three callers.
  # Do not delete without deleting call_haiku with it.
```

- [ ] **Step 7: Prove the worker is clean and run the suite**

```
grep -rn 'anthropic\|api\.anthropic\.com\|claude-' --include='*.py' workers/intake-agent
```
Expected: **nothing**.

Run: `make test-intake-agent`
Expected: **14 + 10 = 24 passed**. Paste the summary line.

- [ ] **Step 8: Self-review and commit**

```
git add -A workers/intake-agent litellm-config.yaml
git commit -m "feat(intake-agent): repoint the LLM client at the gateway

The twin of feedback-agent's client, same change. call_sonnet ->
intake-agent-sonnet (sonnet-4-6 -> sonnet-5, the documented bump) for both
production sites (src/pipeline.py:100, :120). call_haiku -> intake-agent-haiku;
it has no caller (recon B8) and is KEPT because post-repoint it is two lines
naming an alias, it keeps this file symmetric with feedback-agent where the same
method has three callers, and deleting it would orphan the alias and discard the
tier record. litellm-config.yaml now says so at the alias.

cached_prefix DELETED, not translated: never passed by any caller, and the
Anthropic cache_control block it built (anthropic.py:53-56) was unreachable. The
spec's prompt-caching risk does not apply here — nothing was being cached.

Also deleted: the 429/5xx backoff loop, superseded by litellm's num_retries.

tests/test_handler_warm.py needed two patch-string edits; test_pipeline.py and
test_screenable_flag.py stub at method level and were unaffected.

intake-agent: <N> passed."
```

---

### Task 6: intake-agent — pin the loud-failure paths

Unlike feedback-agent, **both intake-agent call sites already fail correctly** — verified end to end, and this task's job is to prove it and keep it that way, not to change behaviour.

- **I1** `pipeline.py:100` → `_parse_rounds_json` (`:162-183`): `json.loads("")` raises `JSONDecodeError`; the function additionally raises on a valid-JSON reply missing `rounds`, on an empty `rounds` array, and on any round missing `name`, `category` or `skills`. It coerces only `duration_minutes` (`:181-182`), which is a formatting default, not a content one.
- **I2** `pipeline.py:120` → `_parse_round_details_json` (`:185-201`): same, plus explicit raises on missing `guidelines` and missing `feedback_questions`.
- Both propagate to `production/handler.py:74`, whose `except Exception` builds `detail = f"{type(e).__name__}: {e}"` (`:76`), logs `worker_failed` with `exc_info=True`, calls `supabase.mark_session_failed(session_id, detail)` (`:85`) and returns `"failed"`.

**This is the behaviour phase 4b's `synthesize` site lacks and phase 5's judge/verdict sites lacked.** It is worth a regression test precisely because it is the exception in this codebase.

**Files:**
- Create: `workers/intake-agent/tests/test_degraded_reply.py`

**Interfaces:** none. No source change is expected. If a test in this task requires one, that is a finding — record it.

- [ ] **Step 1: Write the tests**

Six tests, all through `IntakePipelineV2` with an `AsyncMock` client, asserting the *persisted* outcome rather than the raised type:

1. `EmptyLLMReply` at I1 → `handler` returns `"failed"` and `mark_session_failed` is awaited with a detail containing `EmptyLLMReply`.
2. `""` at I1 → same, detail contains `JSONDecodeError`.
3. Valid JSON without `"rounds"` at I1 → same, detail contains `"rounds"`.
4. `EmptyLLMReply` at I2 (rounds succeed, details fail) → `"failed"`, and **no partial interview plan is finalized** — assert `supabase.finalize_interview_plan` was **not** awaited. This is the one that matters: a half-written plan would be the intake-agent equivalent of phase 4b's blank prefill.
5. Valid JSON without `"guidelines"` at I2 → same.
6. A degraded reply **never** reaches `finalize_interview_plan` with an empty `rounds` list.

- [ ] **Step 2: Run test to verify it passes**

Run: `make test-intake-agent`
Expected: **24 + 6 = 30 passed**.

These should pass **without any source change**. If any fails, the "already safe" analysis above is wrong for that path — **fix the source, and correct the degraded-reply table in this plan** rather than adjusting the test to match current behaviour.

- [ ] **Step 3: Self-review and commit**

```
git add -A workers/intake-agent
git commit -m "test(intake-agent): pin that a degraded LLM reply fails loudly

Both call sites already do the right thing — _parse_rounds_json and
_parse_round_details_json raise on an empty or structurally wrong reply, and
handler.process_intake_v2 persists the cause via mark_session_failed. That is the
exception in this codebase, not the rule (see the six sites Task 3 had to fix),
so it gets a regression test.

The load-bearing one: a failure at the round-details stage must not finalize a
partial interview plan.

No source change required.

intake-agent: <N> passed."
```

---

### Task 7: Wiring, config, and end-to-end verification

The code is correct as of Task 6; this makes the deployment correct. Three blockers close here.

**Files:**
- Modify: `docker-compose.yml`, `.env.example`, `litellm-config.yaml`

**Interfaces:** none.

- [ ] **Step 1: Gate both workers on a healthy gateway (blocker B15)**

Verified at HEAD: `docker-compose.yml` gives `depends_on` only to `backend` (`[feedback-agent, intake-agent, intake-context-builder, litellm]`). `feedback-agent` and `intake-agent` have none, so on `make up` they race the gateway.

Add to **both** services:

```yaml
    depends_on:
      litellm:
        condition: service_healthy
```

**`condition: service_healthy`, not a bare list entry** — and this is load-bearing, not tidiness. Tasks 2 and 5 deleted each client's retry loop because litellm owns retries; a bare `depends_on` only orders container *start*, so the first job after `make up` would hit a gateway that is still booting and now has nothing to retry it. `litellm` already declares a healthcheck (`docker-compose.yml:145-150`), so the condition is available.

Do **not** touch `intake-context-builder` — another agent owns it.

- [ ] **Step 2: Document the worker gateway vars (blocker B14)**

The live `.env` defines `LITELLM_MASTER_KEY` but **not** `LLM_GATEWAY_URL`. Both workers use `env_file: [.env]` with no `environment:` block, so:
- `LITELLM_MASTER_KEY` reaches them today. ✓
- `LLM_GATEWAY_URL` does not — and does not need to **inside compose**, because the settings default is `http://litellm:4000`, which is the service name. ✓
- A **host** process (a script, a manual `python -m pytest` outside the test image, a live smoke run) gets the container-only default and fails to connect.

In `.env.example`, under the existing `# --- LLM gateway ---` block (`:128-131`), append:

```
# Both background workers (feedback-agent, intake-agent) read LLM_GATEWAY_URL and
# LITELLM_MASTER_KEY from this file via compose's env_file. Inside compose the
# default http://litellm:4000 is already correct, which is why the live .env has
# never needed the line. Anything running on the HOST — a smoke script, a manual
# pytest outside the test images — must export LLM_GATEWAY_URL=http://localhost:4000
# or it will try to resolve the compose service name and fail.
```

**Do not add `LLM_GATEWAY_URL` to `.env`** — `.env` is not committed, and the compose default is already right. Document it, do not smuggle a value into a tracked file.

- [ ] **Step 3: Comment the four worker aliases in `litellm-config.yaml`**

Above `feedback-haiku` (`:148`): name it as the tier record for `src/services/interview.py:135,151` and `src/services/verdict.py:44` — three haiku workloads, and the alias resolves to the byte-identical `claude-haiku-4-5-20251001` those sites used before the flip.

Above `feedback-sonnet` (`:154`): name the seven sonnet workloads it serves.

Above `feedback-condense` (`:127`): mark it **reserved and unused**, naming `workers/feedback-agent/src/services/feedback.py:99` as the workload it exists for — one call per topic per interview, this worker's highest-volume sonnet call — and state that pointing that site at it is a one-line follow-up, deliberately not taken in this phase because it would need a third method on a client that is intentionally symmetric with intake-agent's.

(`intake-agent-haiku`'s comment landed in Task 5 Step 6; `intake-agent-sonnet` gets the same treatment as `feedback-sonnet`.)

- [ ] **Step 4: Rebuild, restart, and verify the stack**

```
docker compose up -d litellm
docker compose up -d --build feedback-agent intake-agent
make verify
```

`make verify` must show all ten services `ok`, including `litellm` authenticating. The feedback image carries torch + sentence-transformers (~1.4 GB) — its rebuild is slow; do not interpret that as a hang. **macOS has no `timeout` binary; do not wrap these commands in it.**

- [ ] **Step 5: Confirm the backend baseline is untouched**

Run: `make test` (from the repo root)
Expected: **2185 passed, 5 skipped**.

Nothing in this plan touches `backend/`, `intake-core/`, `llm-core/` or `voice-agent/`, so this should be a no-op — which is exactly why it is worth running once. **Paste the count.** If it moved, this plan did something it did not intend and Task 7 does not ship.

- [ ] **Step 6: Live end-to-end verification (recommended; ~2 billed calls)**

`make verify` only proves each container answers `/health`. It would stay green with a client that 401s on every request, because both workers log LLM failures rather than surfacing them at the health endpoint. Prove the wire instead:

```
docker compose exec feedback-agent python -c "
import asyncio
from src.clients.llm import LLMGatewayClient
async def main():
    async with LLMGatewayClient() as c:
        print('haiku :', (await c.call_haiku('Reply with the single word: ready'))[:40])
        print('sonnet:', (await c.call_sonnet('Reply with the single word: ready'))[:40])
asyncio.run(main())
"
docker compose exec intake-agent python -c "
import asyncio
from src.clients.llm import LLMGatewayClient
async def main():
    async with LLMGatewayClient() as c:
        print('sonnet:', (await c.call_sonnet('Reply with the single word: ready'))[:40])
asyncio.run(main())
"
```

Both must print a real reply. Record the output in the commit. **If it cannot be run in the environment, say so explicitly rather than substituting `make verify` and calling the task verified.**

- [ ] **Step 7: Self-review, commit, and update the checkpoint**

```
git add docker-compose.yml .env.example litellm-config.yaml
git commit -m "chore(workers): gate feedback-agent and intake-agent on a healthy gateway

depends_on: {litellm: {condition: service_healthy}} for both. Not tidiness —
phases 5/6 deleted each client's retry loop because litellm owns retries, so a
worker that starts before the gateway is up now has nothing to retry it.

Documents in .env.example that LLM_GATEWAY_URL is unset in the live .env and does
not need to be inside compose (the default is the service name), but must be
exported for anything running on the host.

Comments the four worker aliases with the tier each preserves, and marks
feedback-condense reserved-and-unused against src/services/feedback.py:99.

make verify: ten services ok. Backend unchanged: 2185 passed, 5 skipped.
Live gateway calls verified: <paste>."
```

Then update `.superpowers/sdd/CHECKPOINT.md`: mark phases 5 and 6 **DONE**; record the two new suite baselines and their exact commands; record that **B5 is closed for phases 5/6 by the httpx-repoint decision but remains open for phase 4b**; record that **B6 was settled by deletion**, with the subset-duplicate evidence; record that **B13 is closed for these two workers** by the new Makefile targets and remains open for `intake-core`, `llm-core`, `intake-context-builder` and `voice-agent`; and record the two orphan aliases and why each was kept.

---

## Definition of Done

- [ ] `grep -rn 'anthropic\|api\.anthropic\.com\|claude-' --include='*.py' workers/feedback-agent workers/intake-agent` returns **nothing**.
- [ ] `grep -rn 'x-api-key\|anthropic-version' --include='*.py' workers/` returns nothing for these two workers.
- [ ] No file in either worker names a provider model id; all four aliases resolve to the tier their call sites used at HEAD, per the Model alias map.
- [ ] `make test-feedback-agent` → **60 passed** (baseline 34 + 26).
- [ ] `make test-intake-agent` → **30 passed** (baseline 14 + 16).
- [ ] `make test` (repo root) → **2185 passed, 5 skipped**, unchanged.
- [ ] Every call site in the degraded-reply table either fails loudly or is covered by a guard keyed on the key it reads, and **no handler swallows `EmptyLLMReply` into a plausible default**.
- [ ] `src/api/server.py`, `src/api/__init__.py` and `src/ui/` are gone; the two Streamlit error strings point at `local.api.app:app`.
- [ ] `call_haiku_sync`, `call_sonnet_sync` and `cached_prefix` are gone.
- [ ] `docker compose up -d --build feedback-agent intake-agent` succeeds and `make verify` shows all ten services `ok`.
- [ ] Both `production/Dockerfile`s still build from their own directory as context — **the Lambda deploy path is not broken by this phase** (this is the httpx decision's whole point; confirm by reading them, they should be untouched).
- [ ] A live call through the gateway succeeded from inside each container, or its absence is stated explicitly.
- [ ] No secret, key, cert or `.env` file is committed.
- [ ] Seven commits, one per task, each self-reviewed, each with its suite count pasted.
- [ ] `.superpowers/sdd/CHECKPOINT.md` updated after **every** task, not once at the end.
