"""Calendar-Intelligence internals.

This package decomposes the historical god-modules into focused units:

  - ``policy``   : single source of truth for detection-status transitions,
                   the derived confirmable/terminal/attachable status sets, and
                   the confidence-tier thresholds (UI + detection).
  - ``matching`` : pure heuristics (title/name extraction + fuzzy match,
                   attendee/email hints, timezone coercion, role/location
                   similarity, scoring, time formatting).
  - ``blocks``   : Slack Block Kit builders.

``app.services.calendar_intelligence_service`` re-exports every public name
from ``matching`` and ``blocks`` so existing import sites keep working
unchanged. This is a behavior-preserving decomposition.
"""
