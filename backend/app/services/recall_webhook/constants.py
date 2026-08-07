"""
Single source of truth for Recall webhook constants.

If you change `RECALL_BOT_NAME` in config, you MUST add its lowercased form to
`BOT_SPEAKER_NAMES` below AND to `_BOT_SPEAKER_NAMES` in
`workers/feedback-agent/src/clients/supabase.py`. The two sets must agree.

This is enforced at startup by a validator in `app/config.py`, because getting
it wrong is silent and expensive: the bot's own utterances get counted as
interviewer feedback, which auto-triggers feedback processing on empty rounds.
"""

from typing import Final


# Lowercased speaker labels that must NEVER be counted as interviewer feedback.
# The bot's own utterances appear under these names in Recall transcript
# segments; letting them through auto-triggers the feedback worker on rounds
# where no human actually said anything.
BOT_SPEAKER_NAMES: Final[frozenset[str]] = frozenset({
    "scout",
    "scout ai",
    "scout interview assistant",
})


# Recall bot lifecycle states where we still consider the bot "active" —
# any state outside this set means the bot is no longer running.
ACTIVE_BOT_STATUSES: Final[tuple[str, ...]] = (
    "created",
    "joining",
    "in_waiting_room",
    "in_call_not_recording",
    "in_call_recording",
)


# Recall sends `bot.status_change` events with a `code` field; we map each
# code to our own DB status. v1 used the same map (`STATUS_MAP` in
# `webhooks/recall.py`); we keep the values identical so v1- and
# v2-scheduled bots write consistent statuses to the shared `recall_bots`
# table.
BOT_STATUS_TO_DB: Final[dict[str, str]] = {
    "joining_call":          "joining",
    "in_waiting_room":       "in_waiting_room",
    "in_call_not_recording": "in_call_not_recording",
    "in_call_recording":     "in_call_recording",
    "call_ended":            "call_ended",
    "done":                  "done",
    "fatal":                 "failed",
}


# Sub-codes that mean "the bot was prevented from joining the call". When
# any of these appear on a `fatal` / `call_ended` event, we fire the
# not-admitted notifier.
_NOT_ADMITTED_KEYWORDS: Final[tuple[str, ...]] = (
    "waiting_room",
    "denied",
    "rejected",
    "not_admitted",
)


def is_not_admitted_sub_code(sub_code: str | None) -> bool:
    """True if the Recall sub_code indicates the bot was blocked from
    entering the call (waiting-room timeout, host denied, etc.)."""
    if not sub_code:
        return False
    sc = sub_code.lower()
    return any(kw in sc for kw in _NOT_ADMITTED_KEYWORDS)


# `partial feedback` thresholds — used by the recording handler to decide
# whether the recruiter dictated enough feedback during the call to skip
# the post-interview "add feedback" email and go straight to the Lambda.
# Match v1 verbatim.
PARTIAL_MIN_INTERVIEWER_TURNS: Final[int] = 1
PARTIAL_MIN_INTERVIEWER_CHARS: Final[int] = 150


# Recall webhook event types we care about. Anything else is logged and
# ignored at the dispatcher level.
class EventType:
    # Main webhook endpoint (`POST /webhooks/recall`)
    BOT_STATUS_CHANGE = "bot.status_change"

    # Realtime webhook endpoint (`POST /webhooks/recall/realtime`)
    PARTICIPANT_JOIN = "participant_events.join"
    PARTICIPANT_LEAVE = "participant_events.leave"
    CHAT_MESSAGE = "participant_events.chat_message"
    TRANSCRIPT_DATA = "transcript.data"
