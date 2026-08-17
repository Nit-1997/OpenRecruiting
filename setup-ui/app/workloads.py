"""The 27 gateway aliases: what each one is for, and which tier it must stay on.

THIS TABLE IS THE CONTRACT. `litellm-config.yaml` is generated from it, so every
comment the hand-written file carried lives here now — and they are not
decoration. Each one records a decision that was expensive to make and is cheap
to undo by accident. The file that replaced them opened with a warning that says
it best: an alias must resolve to the same TIER the call site uses today, or the
change silently re-prices and re-times a workload while claiming to be a no-op.

Five workloads run the cheap tier. Seventeen run the standard one. Getting that
split from the old file rather than its header matters: the header said three.
It was written when there were three and never updated, and `candidate-detect`
and `parse-role-intent` moved to the cheap tier afterwards. Counting the entries
is how this table was built.

TIERS
  standard — the default model of the default provider
  fast     — the cheap model; falls back to the default when no fast is set
  local    — pinned to Ollama regardless of the default provider. These are A/B
             variants, kept so a workload can be compared against a local model
             without editing anything.
  smoke    — one per configured provider, for the cross-provider live suite.
             Never serves traffic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Workload:
    name: str
    tier: str
    #: Carried verbatim into the generated YAML above the entry. Load-bearing:
    #: these are the only surviving record of several tier decisions.
    comment: str = ""
    #: Rendered above the comment as a section divider, matching the old file.
    section: str = ""


WORKLOADS: tuple[Workload, ...] = (
    Workload(
        "intake-jd",
        "fast",
        "Haiku tier, because Settings.INTAKE_JD_MODEL was claude-haiku-4-5-20251001\n"
        "before it was flipped to this alias. The setting now holds the alias, so\n"
        "this entry is the only remaining record of the tier it has to preserve.",
    ),
    Workload("intake-jd-local", "local"),
    Workload("debrief-chat", "standard"),
    Workload(
        "intake-text",
        "standard",
        "The backend's TEXT intake turn loop, phase 3's main streaming site. Its\n"
        "model id is hardcoded at backend/app/api/v2/routers/intake_text_messages.py\n"
        "(claude-sonnet-4-6), and that one variable feeds BOTH the streamed turn and\n"
        "the coverage tracker spawned beside it, so both move onto this alias\n"
        "together. Distinct from voice-intake on purpose: same job, different\n"
        "transport, and tying them together would mean a voice tuning change\n"
        "silently re-tiers text.",
    ),
    Workload(
        "context-parse-jd",
        "standard",
        "workers/intake-context-builder parse_jd. STANDARD tier — settings.py reads\n"
        "ANTHROPIC_MODEL_SONNET (claude-sonnet-4-6). It must NOT reuse `intake-jd`,\n"
        "which is the cheap tier and belongs to the backend's JD extract: that swap\n"
        "would look like a tidy-up and would quietly re-tier a standard workload\n"
        "onto the cheap model, which is exactly what this file forbids. Sibling of\n"
        "context-synthesize.",
    ),
    Workload("screening-generator", "standard"),
    Workload("screening-assessor", "standard"),
    Workload("persona-reduce", "standard"),
    Workload("route-intent", "standard"),
    Workload("signal-extract", "standard"),
    Workload("resume-extract", "standard"),
    Workload(
        "candidate-detect",
        "fast",
        "Cheap tier today: Settings.CANDIDATE_DETECT_MODEL in backend/app/config.py,\n"
        "whose value was claude-3-5-haiku-latest. Pinned to a tier rather than to a\n"
        "floating '-latest' tag, so the alias is reproducible.",
    ),
    Workload(
        "parse-role-intent",
        "fast",
        "Cheap tier today: backend/app/services/intake/parse_intent_service.py:103,\n"
        "where the model id is hardcoded rather than read from settings. It had no\n"
        "alias at all until this entry.",
    ),
    Workload("end-state", "standard"),
    Workload(
        "voice-intake",
        "standard",
        "v2 intake (main.py) and v1 intake. SENDS TOOLS (INTAKE_TOOLS). A model\n"
        "without native function calling DISABLES intake rather than degrading it:\n"
        "streaming and emulated tools do not compose, so the emulated JSON arrives\n"
        "as plain text and is never parsed into a tool call.",
        section=(
            "The three realtime voice pipelines\n"
            "All three were one setting (voice-agent Settings.voice_llm_model, and\n"
            "before phase 7 voice_anthropic_model, never overridden in .env). The\n"
            "tier is preserved. They are split so one voice workload can be\n"
            "repointed — at a local model, a cheaper tier — without dragging the\n"
            "other two with it. That independence is the deliverable of the gateway\n"
            "migration; they resolve to the same model today, so the split changes\n"
            "what is POSSIBLE, not what happens."
        ),
    ),
    Workload(
        "voice-screening",
        "standard",
        "The screening agent (main.py, ALL_SCREENING_TOOLS). SENDS TOOLS — the same\n"
        "native-function-calling warning as voice-intake above applies here.",
    ),
    Workload("voice-feedback", "standard", "Feedback v1 and feedback v2/RTVI. Sends no tools."),
    Workload("feedback-condense", "standard"),
    Workload("context-synthesize", "standard"),
    Workload(
        "feedback-haiku",
        "fast",
        section=(
            "Per-call tier aliases for the two hand-rolled httpx clients\n"
            "workers/feedback-agent and workers/intake-agent each choose between the\n"
            "cheap and standard tier per call (`call_haiku` / `call_sonnet`, model\n"
            "switch at src/clients/anthropic.py:41-43). One alias per service cannot\n"
            "express that, so each gets a pair and the caller picks the alias where\n"
            "it used to pick a model id. The cheap tiers mirror each service's\n"
            "config/settings.py defaults exactly. The standard tiers deliberately do\n"
            "not: the operator specified claude-sonnet-5, so every standard alias\n"
            "here is a conscious upgrade from the claude-sonnet-4-6 the replaced code\n"
            "used. That is intended, not drift."
        ),
    ),
    Workload("feedback-sonnet", "standard"),
    Workload("intake-agent-haiku", "fast"),
    Workload("intake-agent-sonnet", "standard"),
)

#: Emitted after the smoke aliases, matching the old file's order. `intake-jd-local`
#: is not here because it is a WORKLOAD above, at the position it has always held;
#: this is only the trailing extra. Both keep their `-local` names because
#: `gemma-local` is referenced by name from scripts/verify_local_llm.py and
#: `smoke-local` from llm-core's live suite — renaming them to `-ollama` would
#: break both for no gain.
LOCAL_EXTRAS: tuple[Workload, ...] = (Workload("gemma-local", "local"),)

#: The live cross-provider suite reaches each provider through one alias. Ollama's
#: is `smoke-local` for the same backwards-compatibility reason as above.
SMOKE_ALIAS_NAMES: dict[str, str] = {
    "anthropic": "smoke-anthropic",
    "openai": "smoke-openai",
    "openrouter": "smoke-openrouter",
    "ollama": "smoke-local",
}

#: Aliases that send tools and stream at the same time. A model with no native
#: function calling does not degrade on these — it stops working, because
#: emulated tools and streaming do not compose (llm-core's stream_turn injects
#: the schema but never parses the reply back). The UI refuses to bind one.
STREAMING_TOOL_ALIASES: frozenset[str] = frozenset(
    {"voice-intake", "voice-screening", "intake-text"}
)


def by_name() -> dict[str, Workload]:
    return {w.name: w for w in (*WORKLOADS, *LOCAL_EXTRAS)}


def generated_names(configured_providers: list[str]) -> list[str]:
    """Every alias the generator will emit, in the order it emits them.

    Order is the old file's, so the first regeneration of an existing deployment
    is a no-op diff rather than a 260-line reshuffle nobody can review.
    """
    names = [w.name for w in WORKLOADS]
    names.extend(
        SMOKE_ALIAS_NAMES[p] for p in configured_providers if p in SMOKE_ALIAS_NAMES
    )
    names.extend(w.name for w in LOCAL_EXTRAS)
    return names
