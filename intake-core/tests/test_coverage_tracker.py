"""Test the coverage tracker runner — async call to Sonnet, apply patch via RPC."""

from unittest.mock import MagicMock, AsyncMock, patch
import json
import pytest

from intake_core.coverage_tracker import run_coverage_tracker, _is_async_client


@pytest.mark.asyncio
async def test_runner_calls_anthropic_and_applies_patch():
    mock_sb = MagicMock()
    mock_sb.rpc = AsyncMock()  # async client → uses aload_session / aupdate_current_answers
    mock_anthropic = AsyncMock()
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps({
            "q4_must_haves": {"status": "discussed", "extraction_confidence": "high", "text": "Python"}
        }))]
    )
    session_row = {
        "id": "sess-1",
        "current_answers": {"q4_must_haves": {"status": "untouched", "text": None}},
        "turns": [{"role": "user", "content": "Python is the must-have", "idx": 5}],
    }
    with patch("intake_core.coverage_tracker.aload_session", new=AsyncMock(return_value=session_row)), \
         patch("intake_core.coverage_tracker.aupdate_current_answers", new=AsyncMock()) as mock_update:
        result = await run_coverage_tracker(
            supabase_client=mock_sb,
            anthropic_client=mock_anthropic,
            model="claude-sonnet-4-6",
            session_id="sess-1",
            last_user_turn="Python is the must-have",
        )
    assert result["ok"] is True
    mock_anthropic.messages.create.assert_called_once()
    mock_update.assert_called_once()
    call = mock_update.call_args
    patch_arg = call[0][2]
    assert "q4_must_haves" in patch_arg


@pytest.mark.asyncio
async def test_runner_skips_apply_on_empty_patch():
    mock_sb = MagicMock()
    mock_sb.rpc = AsyncMock()
    mock_anthropic = AsyncMock()
    mock_anthropic.messages.create.return_value = MagicMock(content=[MagicMock(text="{}")])
    with patch("intake_core.coverage_tracker.aload_session", new=AsyncMock(return_value={"id": "s", "current_answers": {}, "turns": []})), \
         patch("intake_core.coverage_tracker.aupdate_current_answers", new=AsyncMock()) as mock_update:
        result = await run_coverage_tracker(
            supabase_client=mock_sb, anthropic_client=mock_anthropic,
            model="x", session_id="s", last_user_turn="hello",
        )
    assert result["ok"] is True
    assert result["applied"] is False
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_runner_swallows_llm_failure():
    """A tracker failure must never crash the caller (fire-and-forget)."""
    mock_sb = MagicMock()
    mock_sb.rpc = AsyncMock()
    mock_anthropic = AsyncMock()
    mock_anthropic.messages.create.side_effect = Exception("anthropic down")
    with patch("intake_core.coverage_tracker.aload_session", new=AsyncMock(return_value={"id": "s", "current_answers": {}, "turns": []})):
        result = await run_coverage_tracker(
            supabase_client=mock_sb, anthropic_client=mock_anthropic,
            model="x", session_id="s", last_user_turn="hi",
        )
    assert result["ok"] is False
    assert "anthropic down" in result["error"]


@pytest.mark.asyncio
async def test_runner_does_not_overwrite_agent_writes():
    """If a qid already has higher-quality content, tracker should still merge but
    the persistence layer's merge-don't-clobber semantics keep agent writes safe.
    Tracker just emits the patch; merge_answers handles deep merge."""
    mock_sb = MagicMock()
    mock_sb.rpc = AsyncMock()
    mock_anthropic = AsyncMock()
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps({"q4_must_haves": {"status": "discussed"}}))]
    )
    with patch("intake_core.coverage_tracker.aload_session", new=AsyncMock(return_value={"id": "s", "current_answers": {}, "turns": []})), \
         patch("intake_core.coverage_tracker.aupdate_current_answers", new=AsyncMock()) as mock_update:
        result = await run_coverage_tracker(
            supabase_client=mock_sb, anthropic_client=mock_anthropic,
            model="x", session_id="s", last_user_turn="hi",
        )
    assert result["ok"] is True
    patch_arg = mock_update.call_args[0][2]
    # patch has only status, not text — so existing text is preserved at the DB layer
    assert "text" not in patch_arg["q4_must_haves"]


# ---------------------------------------------------------------------------
# _is_async_client detection
# ---------------------------------------------------------------------------

def test_is_async_client_true_for_async_rpc():
    """SupabaseAdminClient has an async rpc — should return True."""
    client = MagicMock()
    client.rpc = AsyncMock()
    assert _is_async_client(client) is True


def test_is_async_client_false_for_sync_rpc():
    """supabase-py create_client has a sync rpc — should return False."""
    client = MagicMock()
    client.rpc = MagicMock()  # regular (sync) mock
    assert _is_async_client(client) is False


def test_is_async_client_false_when_no_rpc():
    """Clients without rpc attribute default to False."""
    assert _is_async_client(object()) is False


# ---------------------------------------------------------------------------
# Sync client path (voice agent — supabase-py create_client)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_runner_sync_client_applies_patch():
    """Voice agent passes a sync supabase-py client; tracker must load + apply via sync helpers."""
    sync_sb = MagicMock()
    sync_sb.rpc = MagicMock()  # sync rpc → _is_async_client returns False

    mock_anthropic = AsyncMock()
    mock_anthropic.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps({
            "q4_must_haves": {"status": "discussed", "extraction_confidence": "high", "text": "Python"}
        }))]
    )
    session_row = {
        "id": "sess-voice-1",
        "current_answers": {"q4_must_haves": {"status": "untouched", "text": None}},
        "turns": [],
    }

    with patch("intake_core.coverage_tracker.load_session", return_value=session_row) as mock_load, \
         patch("intake_core.coverage_tracker.update_current_answers") as mock_update:
        result = await run_coverage_tracker(
            supabase_client=sync_sb,
            anthropic_client=mock_anthropic,
            model="claude-sonnet-4-6",
            session_id="sess-voice-1",
            last_user_turn="Python is the must-have",
            debounce_ms=0,
        )

    assert result["ok"] is True
    assert result["applied"] is True
    mock_load.assert_called_once_with(sync_sb, "sess-voice-1")
    mock_update.assert_called_once()
    patch_arg = mock_update.call_args[0][2]
    assert "q4_must_haves" in patch_arg


@pytest.mark.asyncio
async def test_runner_sync_client_load_failure_is_swallowed():
    """A sync load_session exception must not propagate — returns ok=False."""
    sync_sb = MagicMock()
    sync_sb.rpc = MagicMock()

    with patch("intake_core.coverage_tracker.load_session", side_effect=Exception("db timeout")):
        result = await run_coverage_tracker(
            supabase_client=sync_sb,
            anthropic_client=AsyncMock(),
            model="x",
            session_id="s",
            last_user_turn="hi",
            debounce_ms=0,
        )

    assert result["ok"] is False
    assert "db timeout" in result["error"]
    assert result["applied"] is False


@pytest.mark.asyncio
async def test_runner_sync_client_skips_apply_on_empty_patch():
    """Sync path: empty patch → ok=True, applied=False, update not called."""
    sync_sb = MagicMock()
    sync_sb.rpc = MagicMock()

    mock_anthropic = AsyncMock()
    mock_anthropic.messages.create.return_value = MagicMock(content=[MagicMock(text="{}")])

    with patch("intake_core.coverage_tracker.load_session", return_value={"id": "s", "current_answers": {}, "turns": []}), \
         patch("intake_core.coverage_tracker.update_current_answers") as mock_update:
        result = await run_coverage_tracker(
            supabase_client=sync_sb,
            anthropic_client=mock_anthropic,
            model="x",
            session_id="s",
            last_user_turn="hi",
            debounce_ms=0,
        )

    assert result["ok"] is True
    assert result["applied"] is False
    mock_update.assert_not_called()
