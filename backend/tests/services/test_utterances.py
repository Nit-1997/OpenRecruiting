"""Characterization tests for the in-memory utterance buffer."""

from app.services.recall_webhook import utterances as u


def setup_function():
    u._UTTERANCES.clear()


def test_append_and_get_snapshot_is_copy():
    u.append_utterance("bot1", "p1", "hello", 1000)
    snap = u.get_utterances("bot1")
    assert snap == {"p1": "hello"}
    snap["p1"] = "mutated"  # must not affect the live buffer
    assert u.get_utterances("bot1") == {"p1": "hello"}


def test_append_merges_existing():
    u.append_utterance("bot1", "p1", "hello", 1000)
    u.append_utterance("bot1", "p1", "world", 1000)
    assert u.get_utterances("bot1") == {"p1": "hello world"}


def test_append_truncates_from_left():
    u.append_utterance("bot1", "p1", "abcdefghij", 5)
    assert u.get_utterances("bot1")["p1"] == "fghij"


def test_append_ignores_blank_inputs():
    u.append_utterance("", "p1", "x", 100)
    u.append_utterance("bot1", "", "x", 100)
    u.append_utterance("bot1", "p1", "", 100)
    assert u.get_utterances("bot1") == {}


def test_get_unknown_bot_empty():
    assert u.get_utterances("nope") == {}


def test_total_chars_sums_participants():
    u.append_utterance("bot1", "p1", "abc", 100)
    u.append_utterance("bot1", "p2", "de", 100)
    assert u.total_chars("bot1") == 5
    assert u.total_chars("nope") == 0


def test_clear_utterances():
    u.append_utterance("bot1", "p1", "x", 100)
    u.clear_utterances("bot1")
    assert u.get_utterances("bot1") == {}
    u.clear_utterances("nonexistent")  # no error
