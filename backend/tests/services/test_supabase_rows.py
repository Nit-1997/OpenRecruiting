"""Unit tests for the shared Supabase row helpers.

BE-F5: consolidate the ~4 copies of `_first_row`/`_first_inserted`, the ~2 copies
of `_is_unique_violation`, and the ~2 copies of `_now_iso` into one module so the
duplicating service files can adopt behaviour-preserving helpers later.

The existing copies live in:
- app/services/intake_session_service.py       (_first_inserted takes the response obj, reads .data)
- app/services/intake_publish_service.py        (identical to session)

`first_row` therefore supports the UNION: a response-like object exposing `.data`,
OR a raw list / dict / None passed directly.
"""

from datetime import datetime, timezone

from app.services._supabase_rows import first_row, is_unique_violation, now_iso


class _Resp:
    """Minimal stand-in for a Supabase TableResponse — exposes only `.data`."""

    def __init__(self, data):
        self.data = data


# ---------------------------------------------------------------------------
# first_row
# ---------------------------------------------------------------------------


def test_first_row_response_with_rows_returns_first():
    """`_first_inserted` shape: response object with a non-empty list `.data`."""
    resp = _Resp([{"id": "1"}, {"id": "2"}])
    assert first_row(resp) == {"id": "1"}


def test_first_row_response_empty_list_returns_none():
    assert first_row(_Resp([])) is None


def test_first_row_response_none_data_returns_none():
    assert first_row(_Resp(None)) is None


def test_first_row_response_single_dict_returns_dict():
    """SupabaseAdminClient single-row shape: `.data` is a dict, not a list."""
    resp = _Resp({"id": "1"})
    assert first_row(resp) == {"id": "1"}


def test_first_row_raw_list_returns_first():
    """`_first_row` shape: raw `.data` list passed directly (no wrapping response)."""
    assert first_row([{"id": "1"}, {"id": "2"}]) == {"id": "1"}


def test_first_row_raw_empty_list_returns_none():
    assert first_row([]) is None


def test_first_row_none_returns_none():
    assert first_row(None) is None


def test_first_row_raw_dict_returns_dict():
    assert first_row({"id": "1"}) == {"id": "1"}


# ---------------------------------------------------------------------------
# is_unique_violation
# ---------------------------------------------------------------------------


def test_is_unique_violation_message_duplicate_key():
    """Replicates existing message-based detection: 'duplicate key' substring."""
    exc = Exception("duplicate key value violates unique constraint")
    assert is_unique_violation(exc) is True


def test_is_unique_violation_message_unique():
    """Replicates existing message-based detection: 'unique' substring."""
    exc = Exception("UNIQUE constraint failed")
    assert is_unique_violation(exc) is True


def test_is_unique_violation_sqlstate_23505_code():
    """Superset: an exc carrying the Postgres unique-violation SQLSTATE code."""

    class PGError(Exception):
        code = "23505"

    assert is_unique_violation(PGError("some opaque text")) is True


def test_is_unique_violation_other_code_false():
    class PGError(Exception):
        code = "23503"  # foreign_key_violation

    assert is_unique_violation(PGError("foreign key constraint violated")) is False


def test_is_unique_violation_unrelated_message_false():
    assert is_unique_violation(Exception("connection reset by peer")) is False


# ---------------------------------------------------------------------------
# now_iso
# ---------------------------------------------------------------------------


def test_now_iso_returns_str():
    assert isinstance(now_iso(), str)


def test_now_iso_is_timezone_aware_utc():
    parsed = datetime.fromisoformat(now_iso())
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)
