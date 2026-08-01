"""In-memory registry of active Pipecat sessions keyed by session_id."""

from unittest.mock import MagicMock

import pytest

from src.intake.session_registry import (
    SessionRegistry,
    SessionNotFound,
)


def test_register_and_get_session():
    reg = SessionRegistry()
    task = MagicMock(name="task")
    reg.register(session_id="s1", task=task)
    assert reg.get("s1") is task


def test_get_unknown_raises():
    reg = SessionRegistry()
    with pytest.raises(SessionNotFound):
        reg.get("nope")


def test_unregister_removes_entry():
    reg = SessionRegistry()
    reg.register(session_id="s1", task=MagicMock())
    reg.unregister("s1")
    with pytest.raises(SessionNotFound):
        reg.get("s1")


def test_unregister_unknown_is_noop():
    reg = SessionRegistry()
    reg.unregister("never-registered")  # must not raise


def test_replace_existing_logs_and_overwrites():
    """If a session_id is registered twice (e.g., reconnect mid-flight), the second
    registration wins. The first task is the caller's responsibility to cancel."""
    reg = SessionRegistry()
    t1 = MagicMock(name="t1")
    t2 = MagicMock(name="t2")
    reg.register(session_id="s1", task=t1)
    reg.register(session_id="s1", task=t2)
    assert reg.get("s1") is t2
