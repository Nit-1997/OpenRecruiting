"""Shared Supabase row helpers.

BE-F5: a single home for three tiny helpers that were duplicated across several
service files. The duplicating files are NOT modified by this ticket — they are
owned by other lanes and will adopt these helpers in a behaviour-preserving way.

Replicated semantics (verified against the existing copies):

- ``first_row`` unifies the two prior shapes:
  - ``_first_row(data)``      in ``untracked_capture_service`` / ``untracked_import_service``
    accepted the raw ``.data`` value (list | dict | None) directly.
  - ``_first_inserted(result)`` in ``intake_session_service`` / ``intake_publish_service``
    accepted the *response object* and reached into ``result.data``.
  ``first_row`` accepts either: if the argument exposes a ``.data`` attribute it is
  unwrapped, otherwise the argument itself is treated as the data.

- ``is_unique_violation`` keeps the existing message-substring detection
  (``"duplicate key"`` / ``"unique"``, case-insensitive) and additionally matches the
  Postgres unique-violation SQLSTATE ``23505`` when the exception carries a ``code``.

- ``now_iso`` is the offset-aware UTC ISO-8601 helper the existing copies already used
  (``datetime.now(timezone.utc).isoformat()`` — never the naive ``utcnow()``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# Postgres SQLSTATE for unique_violation.
_UNIQUE_VIOLATION_SQLSTATE = "23505"


def first_row(resp: Any) -> Optional[dict]:
    """Return the first row from a Supabase response, else ``None``.

    Accepts either a response-like object exposing ``.data`` (e.g. a PostgREST
    ``TableResponse`` / ``SupabaseAdminClient`` response) or the raw ``.data`` value
    passed directly. The underlying data may be:

    - a ``list``  -> the first element, or ``None`` if empty
    - a ``dict``  -> the dict itself (single-row admin-client shape)
    - ``None`` / anything else -> ``None``
    """
    data = resp.data if hasattr(resp, "data") else resp
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data
    return None


def is_unique_violation(exc: Exception) -> bool:
    """Return ``True`` if ``exc`` represents a Postgres unique-constraint violation.

    Matches the existing copies' message-substring detection (``"duplicate key"`` or
    ``"unique"``, case-insensitive) and also recognises the unique-violation SQLSTATE
    ``23505`` when the exception exposes a ``code`` attribute.
    """
    if getattr(exc, "code", None) == _UNIQUE_VIOLATION_SQLSTATE:
        return True
    message = str(exc).lower()
    return "duplicate key" in message or "unique" in message


def now_iso() -> str:
    """Return the current time as an offset-aware UTC ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
