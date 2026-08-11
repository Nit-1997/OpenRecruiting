"""The message reshaping phase 7 lost, and the transcript it must not corrupt.

Every one of these cases was reproduced live against the gateway before the fix
existed; the two 400s are quoted in normalize_messages_for_gateway's docstring.
These tests are the cheap reproduction — the expensive one is a voice session.
"""
import sys
from unittest.mock import MagicMock

for _name in (
    "pipecat",
    "pipecat.services",
    "pipecat.services.openai",
    "pipecat.services.openai.llm",
    "pipecat.services.deepgram",
    "pipecat.services.deepgram.tts",
    "pipecat.services.deepgram.flux",
    "pipecat.services.deepgram.flux.stt",
):
    sys.modules.setdefault(_name, MagicMock())

from src.pipeline.services import normalize_messages_for_gateway  # noqa: E402


PERSONA = {"role": "system", "content": "You are Scout."}
NUDGE = "Say your brief, warm opening greeting as instructed in your persona."


def test_a_fresh_session_does_not_go_out_with_zero_messages():
    """system + system(nudge) is what main.py sends on a FRESH session. LiteLLM
    hoists both into Anthropic's system param, leaving an empty array:
    400 "at least one message is required"."""
    out = normalize_messages_for_gateway([PERSONA, {"role": "system", "content": NUDGE}])

    assert [m["role"] for m in out] == ["system", "user"]
    assert out[-1]["content"] == NUDGE


def test_a_resumed_session_does_not_end_on_an_assistant_prefill():
    """system + assistant + system(nudge) is what main.py sends when resuming a
    session that already has text-chat turns. After hoisting, the array ends on
    an assistant message, which Anthropic reads as a prefill:
    400 "This model does not support assistant message prefill"."""
    out = normalize_messages_for_gateway([
        PERSONA,
        {"role": "assistant", "content": "Hey, Scout here! Does that overview feel complete?"},
        {"role": "system", "content": "You are resuming this same intake conversation."},
    ])

    assert [m["role"] for m in out] == ["system", "assistant", "user"]


def test_consecutive_same_role_messages_are_merged():
    """The Anthropic adapter merged these too. A converted nudge landing right
    after a real user turn would otherwise send two adjacent user messages."""
    out = normalize_messages_for_gateway([
        PERSONA,
        {"role": "user", "content": "It's a payments role."},
        {"role": "system", "content": "You are running low on time. Wrap up NOW."},
    ])

    assert [m["role"] for m in out] == ["system", "user"]
    assert out[-1]["content"] == "It's a payments role.\n\nYou are running low on time. Wrap up NOW."


def test_a_lone_system_message_becomes_a_user_message():
    """The adapter's len==1 case: a list holding only the persona would leave
    nothing on the wire once LiteLLM hoists it."""
    out = normalize_messages_for_gateway([PERSONA])

    assert out == [{"role": "user", "content": "You are Scout."}]


def test_the_leading_persona_stays_a_system_message():
    """LiteLLM lifts the FIRST system message into Anthropic's system param
    correctly. Converting it would bury the persona in the transcript."""
    out = normalize_messages_for_gateway([
        PERSONA,
        {"role": "user", "content": "Hello."},
    ])

    assert out[0] == PERSONA


def test_the_callers_list_is_never_mutated():
    """THE TRANSCRIPT GUARD, and the reason this lives in the service rather
    than at the call sites.

    The list handed in is the shared LLMContext `messages` that
    TurnPersistFrameProcessor reads to build intake_sessions.turns. If this
    rewrote a kickoff instruction to role "user" in place, the transcript would
    record "Say your brief, warm opening greeting..." as something the RECRUITER
    said, and dedup is by content so it would persist verbatim.
    """
    original = [PERSONA, {"role": "system", "content": NUDGE}]
    before = [dict(m) for m in original]

    normalize_messages_for_gateway(original)

    assert original == before, "the shared messages list was mutated"


def test_a_conversation_already_ending_in_a_user_turn_is_untouched():
    messages = [
        PERSONA,
        {"role": "assistant", "content": "What's the role?"},
        {"role": "user", "content": "Staff Backend Engineer."},
    ]
    assert normalize_messages_for_gateway(messages) == messages


def test_non_string_content_is_not_merged_into_a_string():
    """Tool turns carry list-of-parts content. Concatenating those with `+`
    would raise, or silently produce a malformed message."""
    parts = [{"type": "text", "text": "block"}]
    out = normalize_messages_for_gateway([
        PERSONA,
        {"role": "user", "content": parts},
        {"role": "user", "content": "plain text"},
    ])

    assert [m["role"] for m in out] == ["system", "user", "user"]
    assert out[1]["content"] == parts
