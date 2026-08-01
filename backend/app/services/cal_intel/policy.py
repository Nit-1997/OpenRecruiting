"""Single source of truth for Calendar-Intelligence status + confidence policy.

Before this module, the same status/tier truth was duplicated across the
service (``VALID_TRANSITIONS``, the ``build_detection_blocks`` UI tier literals),
the handler (``CONFIRMABLE_STATUSES`` / ``TERMINAL_STATUSES`` /
``ATTACHABLE_BOT_STATUSES`` plus inline status-set literals in the
``_select_*`` / ``_confirm`` guards and the bot-spin-up check), and the
detection service (``0.85`` / ``0.95`` confidence values). Adding a state or
tier meant editing many places with no compiler help.

Everything below is the SAME values as before — the derived sets are computed
from the one transition graph and verified against the characterization tests.
"""

from __future__ import annotations


class Status:
    """Detection-status string constants (the values stored in
    ``calendar_event_detections.detection_status``)."""

    DETECTED = "detected"
    NOTIFIED = "notified"
    AWAITING_ROLE = "awaiting_role"
    AWAITING_ROUND = "awaiting_round"
    AWAITING_CONFIRM = "awaiting_confirm"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    UNDONE = "undone"
    DISMISSED = "dismissed"
    NOT_INTERVIEW = "not_interview"
    ORPHAN_NO_RESPONSE = "orphan_no_response"
    ORPHAN_ROLE = "orphan_role"
    ORPHAN_ROUND = "orphan_round"
    ORPHAN_CONFIRM = "orphan_confirm"
    EXPIRED = "expired"


# The one transition graph. Keys are source statuses, values the set of
# statuses reachable from them.
VALID_TRANSITIONS: dict[str, set[str]] = {
    Status.DETECTED:           {Status.NOTIFIED},
    Status.NOTIFIED:           {Status.AWAITING_ROLE, Status.AWAITING_ROUND, Status.AWAITING_CONFIRM,
                                Status.CONFIRMED, Status.DISMISSED, Status.NOT_INTERVIEW,
                                Status.ORPHAN_NO_RESPONSE, Status.EXPIRED},
    Status.AWAITING_ROLE:      {Status.AWAITING_ROUND, Status.AWAITING_CONFIRM, Status.CONFIRMED,
                                Status.DISMISSED, Status.ORPHAN_ROLE},
    Status.AWAITING_ROUND:     {Status.AWAITING_CONFIRM, Status.CONFIRMED, Status.DISMISSED,
                                Status.ORPHAN_ROUND},
    Status.AWAITING_CONFIRM:   {Status.CONFIRMED, Status.DISMISSED, Status.ORPHAN_CONFIRM},
    Status.CONFIRMING:         {Status.CONFIRMED},
    Status.CONFIRMED:          {Status.UNDONE},
    Status.ORPHAN_NO_RESPONSE: {Status.NOTIFIED, Status.AWAITING_ROLE, Status.AWAITING_ROUND,
                                Status.AWAITING_CONFIRM, Status.CONFIRMED, Status.DISMISSED,
                                Status.NOT_INTERVIEW, Status.EXPIRED},
    Status.ORPHAN_ROLE:        {Status.AWAITING_ROLE, Status.AWAITING_ROUND, Status.AWAITING_CONFIRM,
                                Status.CONFIRMED, Status.DISMISSED, Status.EXPIRED},
    Status.ORPHAN_ROUND:       {Status.AWAITING_ROUND, Status.AWAITING_CONFIRM, Status.CONFIRMED,
                                Status.DISMISSED, Status.EXPIRED},
    Status.ORPHAN_CONFIRM:     {Status.AWAITING_CONFIRM, Status.CONFIRMED, Status.DISMISSED, Status.EXPIRED},
}


# Terminal states: no further user action is possible. ``confirming`` is the
# in-flight CAS lock state, which is terminal w.r.t. user input even though the
# graph still allows ``confirming -> confirmed`` internally.
TERMINAL_STATUSES: frozenset[str] = frozenset({
    Status.CONFIRMED, Status.CONFIRMING, Status.DISMISSED,
    Status.NOT_INTERVIEW, Status.EXPIRED, Status.UNDONE,
})

# Statuses from which a user can confirm setup: every source that can reach
# ``confirmed`` in the graph, minus the in-flight ``confirming`` lock state.
CONFIRMABLE_STATUSES: frozenset[str] = frozenset(
    {src for src, dests in VALID_TRANSITIONS.items() if Status.CONFIRMED in dests}
    - {Status.CONFIRMING}
)

# Guard used by the ``_select_*`` handlers: a selection is rejected once the
# detection is terminal — but ``confirming`` is allowed through there (the CAS
# lock handles concurrency), so this is TERMINAL minus ``confirming``.
SELECT_LOCKED_STATUSES: frozenset[str] = TERMINAL_STATUSES - {Status.CONFIRMING}

# Guard used by ``_confirm``: a confirm is rejected if already confirmed,
# undone, or mid-confirm.
CONFIRM_LOCKED_STATUSES: frozenset[str] = frozenset({
    Status.CONFIRMED, Status.UNDONE, Status.CONFIRMING,
})


# --- Recall bot statuses (separate domain from detection status) ---

# Bot statuses that are still attachable to a detection (i.e. the bot is live
# or about to be).
ATTACHABLE_BOT_STATUSES: frozenset[str] = frozenset({
    "created",
    "joining",
    "in_waiting_room",
    "in_call_not_recording",
    "in_call_recording",
})

# Bot statuses that mean the bot is still spinning up and can be safely deleted
# on rollback (not yet recording).
BOT_SPINUP_STATUSES: frozenset[str] = frozenset({
    "created",
    "joining",
    "in_waiting_room",
})


class ConfidenceTier:
    """Named confidence thresholds + tier values.

    UI tiers gate the HIGH/MEDIUM/LOW label shown on a detection card.
    Detection tiers are the confidence *values* emitted by the deterministic
    candidate-detection tiers (name match / platform signal).
    """

    # UI label thresholds (used by build_detection_blocks).
    UI_HIGH = 0.8       # confidence > UI_HIGH        -> HIGH
    UI_MEDIUM = 0.5     # confidence >= UI_MEDIUM     -> MEDIUM (else LOW)

    # Candidate-detection emitted confidence values.
    DETECTION_NAME_MATCH = 0.95      # tier 1: tracked-participant name match
    DETECTION_PLATFORM_SIGNAL = 0.85  # tier 2: sole non-host in 2-person call

    @classmethod
    def ui_tier(cls, confidence: float) -> str:
        if confidence > cls.UI_HIGH:
            return "HIGH"
        if confidence >= cls.UI_MEDIUM:
            return "MEDIUM"
        return "LOW"
