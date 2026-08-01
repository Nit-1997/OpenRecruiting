"""Test IntakeManualEditService — stamps manual_edit metadata and merges via RPC."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.services.intake_manual_edit_service import IntakeManualEditService


SESSION_ID = UUID("11111111-1111-1111-1111-111111111111")
USER_ID = UUID("22222222-2222-2222-2222-222222222222")
ORG_ID = UUID("33333333-3333-3333-3333-333333333333")


def _ok_owner(mock_sb):
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.single.return_value.execute_async = AsyncMock(
        return_value=MagicMock(
            data={"id": str(SESSION_ID), "user_id": str(USER_ID), "organization_id": str(ORG_ID)}
        )
    )


def _no_owner(mock_sb):
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.single.return_value.execute_async = AsyncMock(
        return_value=MagicMock(data=None)
    )


@pytest.mark.asyncio
async def test_apply_patch_stamps_manual_edit_metadata():
    mock_sb = MagicMock()
    _ok_owner(mock_sb)
    svc = IntakeManualEditService(supabase_client=mock_sb)
    with patch("app.services.intake_manual_edit_service.aupdate_current_answers", new=AsyncMock()) as mock_update:
        applied = await svc.apply_patch(
            session_id=SESSION_ID, user_id=USER_ID, organization_id=ORG_ID,
            patch={"q4_must_haves": {"text": "Python", "status": "validated"}},
        )
    assert applied == ["q4_must_haves"]
    rpc_patch = mock_update.call_args[0][2]
    entry = rpc_patch["q4_must_haves"]
    assert entry["text"] == "Python"
    assert entry["status"] == "validated"
    assert entry["manual_edit"] is True
    assert entry["edited_by"] == str(USER_ID)
    datetime.fromisoformat(entry["edited_at"].replace("Z", "+00:00"))


@pytest.mark.asyncio
async def test_apply_patch_text_only_does_not_overwrite_status():
    mock_sb = MagicMock()
    _ok_owner(mock_sb)
    svc = IntakeManualEditService(supabase_client=mock_sb)
    with patch("app.services.intake_manual_edit_service.aupdate_current_answers", new=AsyncMock()) as mock_update:
        await svc.apply_patch(
            session_id=SESSION_ID, user_id=USER_ID, organization_id=ORG_ID,
            patch={"q1_role_overview": {"text": "payments infra"}},
        )
    rpc_patch = mock_update.call_args[0][2]
    assert "status" not in rpc_patch["q1_role_overview"]
    assert rpc_patch["q1_role_overview"]["text"] == "payments infra"


@pytest.mark.asyncio
async def test_apply_patch_status_only_does_not_send_text():
    mock_sb = MagicMock()
    _ok_owner(mock_sb)
    svc = IntakeManualEditService(supabase_client=mock_sb)
    with patch("app.services.intake_manual_edit_service.aupdate_current_answers", new=AsyncMock()) as mock_update:
        await svc.apply_patch(
            session_id=SESSION_ID, user_id=USER_ID, organization_id=ORG_ID,
            patch={"q7_team_structure": {"status": "skipped"}},
        )
    rpc_patch = mock_update.call_args[0][2]
    assert "text" not in rpc_patch["q7_team_structure"]
    assert rpc_patch["q7_team_structure"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_apply_patch_raises_lookup_error_when_session_missing():
    mock_sb = MagicMock()
    _no_owner(mock_sb)
    svc = IntakeManualEditService(supabase_client=mock_sb)
    with pytest.raises(LookupError):
        await svc.apply_patch(
            session_id=SESSION_ID, user_id=USER_ID, organization_id=ORG_ID,
            patch={"q1_role_overview": {"text": "x"}},
        )


@pytest.mark.asyncio
async def test_apply_patch_preserves_qid_order():
    mock_sb = MagicMock()
    _ok_owner(mock_sb)
    svc = IntakeManualEditService(supabase_client=mock_sb)
    with patch("app.services.intake_manual_edit_service.aupdate_current_answers", new=AsyncMock()):
        applied = await svc.apply_patch(
            session_id=SESSION_ID, user_id=USER_ID, organization_id=ORG_ID,
            patch={
                "q4_must_haves": {"text": "Python"},
                "q1_role_overview": {"text": "payments"},
                "q9_anything_else": {"status": "skipped"},
            },
        )
    assert applied == ["q4_must_haves", "q1_role_overview", "q9_anything_else"]
