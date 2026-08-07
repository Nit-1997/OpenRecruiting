"""Confidence thresholds shared by candidate detection.

The UI thresholds and the emitted detection confidences live together so a
tier change is a one-line edit rather than a hunt through literals.
"""

from __future__ import annotations


class ConfidenceTier:
    """Named confidence thresholds + tier values.

    UI tiers gate the HIGH/MEDIUM/LOW label shown on a detection card.
    Detection tiers are the confidence *values* emitted by the deterministic
    candidate-detection tiers (name match / platform signal).
    """

    UI_HIGH = 0.8       # confidence > UI_HIGH        -> HIGH
    UI_MEDIUM = 0.5     # confidence >= UI_MEDIUM     -> MEDIUM (else LOW)

    DETECTION_NAME_MATCH = 0.95      # tier 1: tracked-participant name match
    DETECTION_PLATFORM_SIGNAL = 0.85  # tier 2: sole non-host in 2-person call

    @classmethod
    def ui_tier(cls, confidence: float) -> str:
        if confidence > cls.UI_HIGH:
            return "HIGH"
        if confidence >= cls.UI_MEDIUM:
            return "MEDIUM"
        return "LOW"
