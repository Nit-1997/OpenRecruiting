"""Characterization tests for recall_webhook.notifications.notify_bot_not_admitted.

Covers the CAS short-circuit, the happy path, the missing candidate_round /
recruiter early returns, the email-skip-on-no-recruiter-email branch, and the
send-failure CAS revert (success + revert-failure-warns).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.recall_webhook import notifications


def _multi_table_supabase(rows_by_table, cas_data=None):
    """supabase.table(name) -> builder whose execute_async returns the row list
    configured for that table. The update/CAS chain on recall_bots returns
    cas_data when provided (so the CAS guard can pass/fail deterministically)."""
    sb = MagicMock()
    calls = {"recall_bots_update": 0}

    def table(name):
        builder = MagicMock()
        for attr in ("select", "update", "eq", "neq", "is_null", "order"):
            setattr(builder, attr, MagicMock(return_value=builder))
        if name == "recall_bots":
            def exec_async():
                calls["recall_bots_update"] += 1
                return MagicMock(data=cas_data if cas_data is not None else [{"id": "db1"}])
            builder.execute_async = AsyncMock(side_effect=lambda: exec_async())
        else:
            builder.execute_async = AsyncMock(return_value=MagicMock(data=rows_by_table.get(name, [])))
        return builder

    sb.table = MagicMock(side_effect=table)
    return sb


def _full_context_rows():
    return {
        "candidate_rounds": [{"candidate_id": "c1", "round_id": "r1"}],
        "rounds": [{"name": "Round 1", "requisition_id": "req1", "default_interviewer_emails": ["iv@m.ai"]}],
        "requisitions": [{"role_title": "Engineer", "created_by": "rec1"}],
        "candidates": [{"name": "Alice", "email": "alice@x.com"}],
        "profiles": [{"email": "rec@m.ai", "full_name": "Rita Cruz"}],
    }


@pytest.mark.asyncio
async def test_cas_already_alerted_short_circuits():
    sb = _multi_table_supabase({}, cas_data=[])  # zero rows -> already alerted
    with patch.object(notifications, "get_supabase_admin_client", return_value=sb):
        await notifications.notify_bot_not_admitted({"id": "db1"})
    # Only the CAS update happened; no email service touched.


@pytest.mark.asyncio
async def test_happy_path_email():
    sb = _multi_table_supabase(_full_context_rows())
    email_svc = MagicMock()
    email_svc.send_templated_email = AsyncMock()
    with patch.object(notifications, "get_supabase_admin_client", return_value=sb), \
         patch.object(notifications, "get_email_service", return_value=email_svc):
        await notifications.notify_bot_not_admitted({"id": "db1", "candidate_round_id": "cr1"})
    email_svc.send_templated_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_candidate_round_id_returns():
    sb = _multi_table_supabase({})
    with patch.object(notifications, "get_supabase_admin_client", return_value=sb):
        await notifications.notify_bot_not_admitted({"id": "db1"})  # no candidate_round_id


@pytest.mark.asyncio
async def test_missing_candidate_round_row_returns():
    rows = {"candidate_rounds": []}
    sb = _multi_table_supabase(rows)
    email_svc = MagicMock(); email_svc.send_templated_email = AsyncMock()
    with patch.object(notifications, "get_supabase_admin_client", return_value=sb), \
         patch.object(notifications, "get_email_service", return_value=email_svc):
        await notifications.notify_bot_not_admitted({"id": "db1", "candidate_round_id": "cr1"})
    email_svc.send_templated_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_recruiter_id_returns():
    rows = _full_context_rows()
    rows["requisitions"] = [{"role_title": "Eng", "created_by": None}]
    sb = _multi_table_supabase(rows)
    email_svc = MagicMock(); email_svc.send_templated_email = AsyncMock()
    with patch.object(notifications, "get_supabase_admin_client", return_value=sb), \
         patch.object(notifications, "get_email_service", return_value=email_svc):
        await notifications.notify_bot_not_admitted({"id": "db1", "candidate_round_id": "cr1"})
    email_svc.send_templated_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_email_skipped_when_no_recruiter_email():
    rows = _full_context_rows()
    rows["profiles"] = [{"email": "", "full_name": "X"}]
    sb = _multi_table_supabase(rows)
    email_svc = MagicMock(); email_svc.send_templated_email = AsyncMock()
    with patch.object(notifications, "get_supabase_admin_client", return_value=sb), \
         patch.object(notifications, "get_email_service", return_value=email_svc):
        await notifications.notify_bot_not_admitted({"id": "db1", "candidate_round_id": "cr1"})
    email_svc.send_templated_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_failure_reverts_cas_marker():
    rows = _full_context_rows()
    sb = _multi_table_supabase(rows)
    email_svc = MagicMock()
    email_svc.send_templated_email = AsyncMock(side_effect=RuntimeError("smtp down"))
    with patch.object(notifications, "get_supabase_admin_client", return_value=sb), \
         patch.object(notifications, "get_email_service", return_value=email_svc):
        # Must not raise; the revert path runs.
        await notifications.notify_bot_not_admitted({"id": "db1", "candidate_round_id": "cr1"})


@pytest.mark.asyncio
async def test_send_failure_revert_failure_warns():
    rows = _full_context_rows()
    # Build a supabase where the revert update itself throws.
    sb = MagicMock()
    state = {"cas_calls": 0}

    def table(name):
        builder = MagicMock()
        for attr in ("select", "update", "eq", "neq", "is_null", "order"):
            setattr(builder, attr, MagicMock(return_value=builder))
        if name == "recall_bots":
            async def exec_async():
                state["cas_calls"] += 1
                if state["cas_calls"] == 1:
                    return MagicMock(data=[{"id": "db1"}])  # CAS won
                raise RuntimeError("revert db error")  # revert update fails
            builder.execute_async = AsyncMock(side_effect=exec_async)
        else:
            builder.execute_async = AsyncMock(return_value=MagicMock(data=rows.get(name, [])))
        return builder

    sb.table = MagicMock(side_effect=table)
    email_svc = MagicMock()
    email_svc.send_templated_email = AsyncMock(side_effect=RuntimeError("smtp down"))
    with patch.object(notifications, "get_supabase_admin_client", return_value=sb), \
         patch.object(notifications, "get_email_service", return_value=email_svc):
        await notifications.notify_bot_not_admitted({"id": "db1", "candidate_round_id": "cr1"})
