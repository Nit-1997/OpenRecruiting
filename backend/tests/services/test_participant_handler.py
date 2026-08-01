"""Characterization tests for recall_webhook.participant_handler:
join tracking, leave drop-detection (completed / JIT / heuristic strategies),
and the small helpers.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.recall_webhook import participant_handler as ph


@pytest.fixture(autouse=True)
def _clear_in_flight():
    ph._detection_in_flight.clear()
    yield
    ph._detection_in_flight.clear()


def _settings(detect=True, conf=0.7, end_state_enabled=True, end_state_conf=0.7, grace=0, voice=False):
    return SimpleNamespace(
        CANDIDATE_DETECT_ENABLED=detect,
        CANDIDATE_DETECT_CONFIDENCE_THRESHOLD=conf,
        END_STATE_DETECT_ENABLED=end_state_enabled,
        END_STATE_CONFIDENCE_THRESHOLD=end_state_conf,
        END_STATE_GRACE_SECONDS=grace,
        VOICE_ENABLED=voice,
    )


class _BG:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **k):
        self.tasks.append((fn, a, k))


# ----------------------- _mark_left -----------------------

def test_mark_left_stamps_and_returns():
    tracked = [{"id": "p1", "left_at": None}, {"id": "p2", "left_at": None}]
    entry = ph._mark_left(tracked, "p1")
    assert entry["left_at"] is not None
    assert tracked[1]["left_at"] is None


def test_mark_left_not_found():
    assert ph._mark_left([{"id": "p1"}], "px") is None


# ----------------------- _drop_from_heuristic -----------------------

def test_heuristic_interviewer_left_no_trigger():
    leaver = {"is_host": True}
    assert ph._drop_from_heuristic([], leaver, "Bob") is False


def test_heuristic_no_interviewer_remaining_no_trigger():
    tracked = [{"id": "p1", "left_at": "t"}]
    leaver = {"id": "p1"}
    assert ph._drop_from_heuristic(tracked, leaver, "Alice") is False


def test_heuristic_non_interviewer_left_with_interviewer_present_triggers():
    tracked = [
        {"id": "p1", "left_at": "t"},  # candidate left
        {"id": "p2", "is_host": True, "left_at": None},  # interviewer present
    ]
    leaver = {"id": "p1"}
    assert ph._drop_from_heuristic(tracked, leaver, "Alice") is True


# ----------------------- _drop_from_completed_detection -----------------------

def test_completed_detection_non_candidate_false():
    bot = {"detected_candidate_participant_id": "pc", "detection_confidence": 0.9}
    out = ph._drop_from_completed_detection(bot, {}, "px", "Bob", _settings())
    assert out is False


def test_completed_detection_low_confidence_none():
    bot = {"detected_candidate_participant_id": "pc", "detection_confidence": 0.3}
    out = ph._drop_from_completed_detection(bot, {}, "pc", "Alice", _settings(conf=0.7))
    assert out is None


def test_completed_detection_interviewer_none():
    bot = {"detected_candidate_participant_id": "pc", "detection_confidence": 0.9}
    out = ph._drop_from_completed_detection(bot, {"is_host": True}, "pc", "Alice", _settings())
    assert out is None


def test_completed_detection_match_true():
    bot = {"detected_candidate_participant_id": "pc", "detection_confidence": 0.95}
    out = ph._drop_from_completed_detection(bot, {}, "pc", "Alice", _settings())
    assert out is True


# ----------------------- _drop_from_jit_detection -----------------------

@pytest.mark.asyncio
async def test_jit_no_result_false():
    bot = {"id": "db1"}
    with patch.object(ph, "get_utterances", return_value={}), \
         patch.object(ph, "run_detection", AsyncMock(return_value=None)):
        out = await ph._drop_from_jit_detection(bot, [], {}, "p1", "Alice", _settings())
    assert out is False


@pytest.mark.asyncio
async def test_jit_match_true():
    bot = {"id": "db1"}
    result = {"candidate_participant_id": "p1", "confidence": 0.9}
    with patch.object(ph, "get_utterances", return_value={"p1": "x"}), \
         patch.object(ph, "run_detection", AsyncMock(return_value=result)), \
         patch.object(ph, "store_detection_result", AsyncMock()):
        out = await ph._drop_from_jit_detection(bot, [], {}, "p1", "Alice", _settings(conf=0.7))
    assert out is True


@pytest.mark.asyncio
async def test_jit_low_confidence_false():
    bot = {"id": "db1"}
    result = {"candidate_participant_id": "p1", "confidence": 0.2}
    with patch.object(ph, "get_utterances", return_value={}), \
         patch.object(ph, "run_detection", AsyncMock(return_value=result)), \
         patch.object(ph, "store_detection_result", AsyncMock()):
        out = await ph._drop_from_jit_detection(bot, [], {}, "p1", "Alice", _settings(conf=0.7))
    assert out is False


@pytest.mark.asyncio
async def test_jit_interviewer_false():
    bot = {"id": "db1"}
    result = {"candidate_participant_id": "p1", "confidence": 0.9}
    with patch.object(ph, "get_utterances", return_value={}), \
         patch.object(ph, "run_detection", AsyncMock(return_value=result)), \
         patch.object(ph, "store_detection_result", AsyncMock()):
        out = await ph._drop_from_jit_detection(bot, [], {"is_host": True}, "p1", "Alice", _settings())
    assert out is False


# ----------------------- handle_participant_join -----------------------

@pytest.mark.asyncio
async def test_join_unknown_bot_returns():
    with patch.object(ph, "get_recall_bot_by_recall_id", AsyncMock(return_value=None)):
        await ph.handle_participant_join("rb1", {"data": {"participant": {"id": "p1"}}})


@pytest.mark.asyncio
async def test_join_appends_and_sets_status_on_first_join():
    bot = {"id": "db1", "tracked_participants": [], "feedback_status": "none"}
    payload = {"data": {"participant": {
        "id": "p1", "name": "Bob", "is_host": True, "platform": "zoom",
        "extra_data": {"microsoft_teams": {"participant_type": "inTenant", "meeting_role": "host"}},
        "email": "bob@m.ai",
    }}}
    with patch.object(ph, "get_recall_bot_by_recall_id", AsyncMock(return_value=bot)), \
         patch.object(ph, "_update_bot", AsyncMock()) as upd:
        await ph.handle_participant_join("rb1", payload)
    update_data = upd.await_args.args[1]
    assert update_data["feedback_status"] == "waiting_for_leave"
    entry = update_data["tracked_participants"][0]
    assert entry["is_tenant"] is True
    assert entry["meeting_role"] == "host"


# ----------------------- handle_participant_leave -----------------------

@pytest.mark.asyncio
async def test_leave_unknown_bot_returns():
    with patch.object(ph, "get_recall_bot_by_recall_id", AsyncMock(return_value=None)):
        await ph.handle_participant_leave("rb1", {"data": {"participant": {"id": "p1"}}}, _BG())


@pytest.mark.asyncio
async def test_leave_not_waiting_status_skips_detection():
    bot = {"id": "db1", "tracked_participants": [{"id": "p1"}], "feedback_status": "completed"}
    trigger = AsyncMock()
    with patch.object(ph, "get_recall_bot_by_recall_id", AsyncMock(return_value=bot)), \
         patch.object(ph, "_update_bot", AsyncMock()), \
         patch.object(ph, "trigger_feedback_collection", trigger):
        await ph.handle_participant_leave("rb1", {"data": {"participant": {"id": "p1"}}}, _BG())
    trigger.assert_not_awaited()


@pytest.mark.asyncio
async def test_leave_candidate_drop_schedules_grace_confirmation():
    """Flag ON (default): a candidate drop must NOT trigger immediately —
    it schedules the grace-delayed `_confirm_end_and_trigger` task."""
    bot = {
        "id": "db1",
        "tracked_participants": [
            {"id": "p1", "left_at": None},
            {"id": "p2", "is_host": True, "left_at": None},
        ],
        "feedback_status": "waiting_for_leave",
        "detection_completed": False,
    }
    bg = _BG()
    trigger = AsyncMock()
    with patch.object(ph, "get_recall_bot_by_recall_id", AsyncMock(return_value=bot)), \
         patch.object(ph, "_update_bot", AsyncMock()), \
         patch.object(ph, "get_settings", lambda: _settings(detect=False, grace=42)), \
         patch.object(ph, "trigger_feedback_collection", trigger):
        await ph.handle_participant_leave("rb1", {"data": {"participant": {"id": "p1", "name": "Alice"}}}, bg)
    # Deferred, not immediate.
    trigger.assert_not_awaited()
    assert len(bg.tasks) == 1
    fn, args, _ = bg.tasks[0]
    assert fn is ph._confirm_end_and_trigger
    # (recall_bot_id, db_id, participant_id, grace_seconds, background_tasks)
    assert args[0] == "rb1"
    assert args[1] == "db1"
    assert args[2] == "p1"
    assert args[3] == 42


@pytest.mark.asyncio
async def test_leave_candidate_drop_flag_off_triggers_immediately():
    """Flag OFF: legacy behaviour — immediate trigger, no scheduled task."""
    bot = {
        "id": "db1",
        "tracked_participants": [
            {"id": "p1", "left_at": None},
            {"id": "p2", "is_host": True, "left_at": None},
        ],
        "feedback_status": "waiting_for_leave",
        "detection_completed": False,
    }
    bg = _BG()
    trigger = AsyncMock()
    with patch.object(ph, "get_recall_bot_by_recall_id", AsyncMock(return_value=bot)), \
         patch.object(ph, "_update_bot", AsyncMock()), \
         patch.object(ph, "get_settings", lambda: _settings(detect=False, end_state_enabled=False)), \
         patch.object(ph, "trigger_feedback_collection", trigger):
        await ph.handle_participant_leave("rb1", {"data": {"participant": {"id": "p1", "name": "Alice"}}}, bg)
    trigger.assert_awaited_once()
    assert bg.tasks == []


# ----------------------- _confirm_end_and_trigger -----------------------


@pytest.mark.asyncio
async def test_drop_phase_mid_does_not_trigger(monkeypatch):
    """Grace re-evaluation returns phase=mid → transient drop → no trigger."""
    triggered = {"called": False}

    async def _verdict(*a, **k):
        from app.services.recall_webhook.end_state import EndStateVerdict
        return EndStateVerdict("mid", 0.9, False, "transient", "llm")
    monkeypatch.setattr(ph.end_state, "evaluate_end_state", _verdict)

    async def _trigger(*a, **k):
        triggered["called"] = True
    monkeypatch.setattr(ph, "trigger_feedback_collection", _trigger)

    # Present, still-waiting bot whose dropped participant remains gone.
    async def _refetch(_rbid):
        return {"id": "bot-1", "candidate_round_id": "cr-1",
                "feedback_status": "waiting_for_leave",
                "tracked_participants": [{"id": 200, "is_host": False, "left_at": "t"}]}
    monkeypatch.setattr(ph, "get_recall_bot_by_recall_id", _refetch)
    monkeypatch.setattr(ph, "get_utterances", lambda _id: {"200": "bye"})
    monkeypatch.setattr(ph, "get_settings", lambda: _settings())

    await ph._confirm_end_and_trigger(
        recall_bot_id="rb-1", db_id="bot-1", dropped_participant_id=200, grace_seconds=0,
        background_tasks=None,
    )
    assert triggered["called"] is False


@pytest.mark.asyncio
async def test_drop_phase_ended_triggers(monkeypatch):
    """Grace re-evaluation returns phase=ended (≥ threshold) with the
    candidate still gone → feedback collection IS triggered."""
    triggered = {"called": False}

    async def _verdict(*a, **k):
        from app.services.recall_webhook.end_state import EndStateVerdict
        return EndStateVerdict("ended", 0.95, False, "closing", "llm")
    monkeypatch.setattr(ph.end_state, "evaluate_end_state", _verdict)

    async def _trigger(*a, **k):
        triggered["called"] = True
    monkeypatch.setattr(ph, "trigger_feedback_collection", _trigger)

    # Present, still-waiting bot whose dropped participant is still gone.
    async def _refetch(_rbid):
        return {"id": "bot-1", "candidate_round_id": "cr-1",
                "feedback_status": "waiting_for_leave",
                "tracked_participants": [{"id": 200, "is_host": False, "left_at": "t"}]}
    monkeypatch.setattr(ph, "get_recall_bot_by_recall_id", _refetch)
    monkeypatch.setattr(ph, "get_utterances", lambda _id: {"200": "bye"})
    monkeypatch.setattr(ph, "get_settings", lambda: _settings())

    await ph._confirm_end_and_trigger(
        recall_bot_id="rb-1", db_id="bot-1", dropped_participant_id=200, grace_seconds=0,
        background_tasks=None,
    )
    assert triggered["called"] is True


# ----------- nested background-task seam (real BackgroundTasks) -----------


@pytest.mark.asyncio
async def test_nested_leaf_task_fires_through_real_background_tasks(monkeypatch):
    """Regression guard for the nested add_task seam.

    `_confirm_end_and_trigger` is scheduled on a REAL `fastapi.BackgroundTasks`;
    after the grace sleep it calls the REAL `trigger_feedback_collection`, which
    (no voice token + reason 'participant_leave' → `_prompt_interviewer`) itself
    calls `background_tasks.add_task(send_feedback_prompt, ...)` while the runner
    is mid-iteration. This proves that nested leaf task actually executes under
    the current Starlette runner. `trigger_feedback_collection` is NOT mocked;
    only the leaf IO (`send_feedback_prompt`) and DB writes are stubbed.
    """
    from fastapi import BackgroundTasks

    from app.services.recall_webhook import end_state as es
    from app.services.recall_webhook import feedback_collection as fc

    bot = {
        "id": "db1",
        "candidate_round_id": "cr-1",
        "voice_session_token": None,
        "feedback_status": "waiting_for_leave",
        "feedback_started_at": None,
        "tracked_participants": [{"id": 200, "is_host": False, "left_at": "t"}],
    }

    leaf = AsyncMock()
    monkeypatch.setattr("app.services.recall_webhook.chat_handler.send_feedback_prompt", leaf)

    # Stub DB writes in both modules so no Supabase call happens.
    monkeypatch.setattr(ph, "_update_bot", AsyncMock())
    monkeypatch.setattr(fc, "_update_bot", AsyncMock())

    # Bot is still present + waiting on re-fetch; dropped participant stays gone.
    monkeypatch.setattr(ph, "get_recall_bot_by_recall_id", AsyncMock(return_value=bot))
    monkeypatch.setattr(ph, "get_utterances", lambda _id: {"200": "bye"})
    monkeypatch.setattr(ph, "get_settings", lambda: _settings(end_state_conf=0.7))
    monkeypatch.setattr(fc, "get_settings", lambda: _settings(end_state_conf=0.7))

    async def _verdict(*a, **k):
        return es.EndStateVerdict("ended", 0.95, False, "closing", "llm")
    monkeypatch.setattr(ph.end_state, "evaluate_end_state", _verdict)

    bg = BackgroundTasks()
    bg.add_task(ph._confirm_end_and_trigger, "rb1", "db1", 200, 0, bg)
    await bg()

    leaf.assert_awaited_once_with("rb1")
