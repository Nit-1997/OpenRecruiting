"""BE-T2 characterization tests for candidate_detection_service.

Pins CURRENT three-tier detection behavior (name match → platform signal →
LLM), the orchestrator gating, the store/flush side effect, and the
retroactive-trigger logic. No production code is modified.

The LLM tier (tier3) and the Supabase store path are mocked at their effect
boundaries so tests are deterministic and never hit the network/clock.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.candidate_detection_service as d


# ---------------------------------------------------------------------------
# Tier 1 — name match (only counts if the participant has spoken)
# ---------------------------------------------------------------------------


def test_tier1_name_match_hit():
    participants = [{"id": 1, "name": "John Smith"}, {"id": 2, "name": "Jane Doe"}]
    utterances = {"1": "I have five years of backend experience."}
    result = d.tier1_name_match("John Smith", participants, utterances)
    assert result is not None
    assert result["candidate_participant_id"] == 1
    assert result["confidence"] == 0.95
    assert result["candidate_name"] == "John Smith"


def test_tier1_name_match_requires_utterances():
    # Name matches but the participant never spoke → no detection.
    participants = [{"id": 1, "name": "John Smith"}]
    result = d.tier1_name_match("John Smith", participants, {})
    assert result is None


def test_tier1_name_match_empty_utterance_string_skipped():
    participants = [{"id": 1, "name": "John Smith"}]
    result = d.tier1_name_match("John Smith", participants, {"1": ""})
    assert result is None


def test_tier1_name_match_no_candidate_name():
    participants = [{"id": 1, "name": "John Smith"}]
    assert d.tier1_name_match("", participants, {"1": "hi"}) is None


def test_tier1_name_match_no_name_participant_skipped():
    participants = [{"id": 1, "name": ""}, {"id": 2, "name": "John Smith"}]
    result = d.tier1_name_match("John Smith", participants, {"2": "hi there now"})
    assert result["candidate_participant_id"] == 2


# ---------------------------------------------------------------------------
# Tier 2 — platform signals (exactly one host/tenant + one non-host)
# ---------------------------------------------------------------------------


def test_tier2_platform_signals_two_person_hit():
    participants = [
        {"id": 1, "name": "Host", "is_host": True},
        {"id": 2, "name": "Candidate", "is_host": False},
    ]
    result = d.tier2_platform_signals(participants)
    assert result is not None
    assert result["candidate_participant_id"] == 2
    assert result["confidence"] == 0.85


def test_tier2_platform_signals_tenant_counts_as_host():
    participants = [
        {"id": 1, "name": "Tenant", "is_tenant": True},
        {"id": 2, "name": "Candidate"},
    ]
    result = d.tier2_platform_signals(participants)
    assert result["candidate_participant_id"] == 2


def test_tier2_platform_signals_not_two_people():
    assert d.tier2_platform_signals([{"id": 1}]) is None
    assert d.tier2_platform_signals([{"id": 1}, {"id": 2}, {"id": 3}]) is None


def test_tier2_platform_signals_both_hosts_none():
    participants = [
        {"id": 1, "is_host": True},
        {"id": 2, "is_host": True},
    ]
    assert d.tier2_platform_signals(participants) is None


def test_tier2_platform_signals_no_host_none():
    participants = [{"id": 1}, {"id": 2}]
    assert d.tier2_platform_signals(participants) is None


# ---------------------------------------------------------------------------
# _is_valid_detection_result — LLM JSON shape validation
# ---------------------------------------------------------------------------


def test_is_valid_detection_result_ok():
    assert d._is_valid_detection_result(
        {"candidate_participant_id": 1, "confidence": 0.9}, "{}"
    ) is True


def test_is_valid_detection_result_missing_keys():
    assert d._is_valid_detection_result({"confidence": 0.9}, "{}") is False


def test_is_valid_detection_result_null_values():
    assert d._is_valid_detection_result(
        {"candidate_participant_id": None, "confidence": 0.9}, "{}"
    ) is False


def test_is_valid_detection_result_not_dict():
    assert d._is_valid_detection_result(["nope"], "[]") is False


# ---------------------------------------------------------------------------
# _build_detection_prompt — deterministic prompt assembly
# ---------------------------------------------------------------------------


def test_build_detection_prompt_includes_participants_and_snippets():
    settings = MagicMock()
    settings.CANDIDATE_DETECT_CHAR_THRESHOLD = 200
    participants = [
        {"id": 1, "name": "Host", "is_host": True, "is_tenant": False},
        {"id": 2, "name": "Cand", "is_host": False, "is_tenant": False},
    ]
    utterances = {"1": "interviewer speaking", "2": "candidate speaking"}
    prompt = d._build_detection_prompt("Cand", participants, utterances, settings)
    assert 'Known candidate name: "Cand"' in prompt
    assert "interviewer speaking" in prompt
    assert "candidate speaking" in prompt
    assert "is_host=True" in prompt


def test_build_detection_prompt_truncates_to_char_threshold():
    settings = MagicMock()
    settings.CANDIDATE_DETECT_CHAR_THRESHOLD = 5
    participants = [{"id": 1, "name": "P", "is_host": False, "is_tenant": False}]
    utterances = {"1": "abcdefghij"}
    prompt = d._build_detection_prompt("P", participants, utterances, settings)
    assert '"abcde"' in prompt
    assert "abcdefghij" not in prompt


# ---------------------------------------------------------------------------
# run_detection — orchestrator gating
# ---------------------------------------------------------------------------


def _settings(**overrides):
    s = MagicMock()
    s.CANDIDATE_DETECT_ENABLED = True
    s.CANDIDATE_DETECT_CHAR_THRESHOLD = 200
    s.CANDIDATE_DETECT_MIN_PARTICIPANTS = 2
    s.CANDIDATE_DETECT_CONFIDENCE_THRESHOLD = 0.9
    s.CANDIDATE_DETECT_MODEL = "candidate-detect"   # a gateway alias since phase 8
    s.ANTHROPIC_API_KEY = "test-key"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


async def test_run_detection_disabled_short_circuits():
    with patch.object(d, "get_settings", return_value=_settings(CANDIDATE_DETECT_ENABLED=False)):
        result = await d.run_detection({"candidate_name": "X", "tracked_participants": []}, {})
    assert result is None


async def test_run_detection_tier1_wins():
    bot = {
        "candidate_name": "John Smith",
        "tracked_participants": [{"id": 1, "name": "John Smith"}],
    }
    with patch.object(d, "get_settings", return_value=_settings()):
        result = await d.run_detection(bot, {"1": "I worked at Acme."})
    assert result["confidence"] == 0.95


async def test_run_detection_tier2_wins_when_tier1_misses():
    bot = {
        "candidate_name": "Nobody Match",
        "tracked_participants": [
            {"id": 1, "name": "Host", "is_host": True},
            {"id": 2, "name": "Candidate"},
        ],
    }
    with patch.object(d, "get_settings", return_value=_settings()):
        result = await d.run_detection(bot, {})
    assert result["confidence"] == 0.85
    assert result["candidate_participant_id"] == 2


async def test_run_detection_tier3_gated_by_min_participants():
    # 3 participants so tier2 is skipped; only 1 has enough chars → below
    # CANDIDATE_DETECT_MIN_PARTICIPANTS → tier3 never runs → None.
    # Names are chosen so names_match() does not substring-match the
    # candidate name (that quirk would otherwise short-circuit at tier1).
    bot = {
        "candidate_name": "Qqqq Wwww",
        "tracked_participants": [
            {"id": 1, "name": "Hostperson"},
            {"id": 2, "name": "Bobby"},
            {"id": 3, "name": "Charles"},
        ],
    }
    utterances = {"1": "x" * 200}
    with patch.object(d, "get_settings", return_value=_settings()):
        with patch.object(d, "tier3_llm_detection", new=AsyncMock()) as mock_t3:
            result = await d.run_detection(bot, utterances)
    assert result is None
    mock_t3.assert_not_called()


async def test_run_detection_tier3_runs_when_enough_talkers():
    bot = {
        "candidate_name": "Qqqq Wwww",
        "tracked_participants": [
            {"id": 1, "name": "Hostperson"},
            {"id": 2, "name": "Bobby"},
            {"id": 3, "name": "Charles"},
        ],
    }
    utterances = {"1": "x" * 200, "2": "y" * 200}
    fake = {"candidate_participant_id": 2, "confidence": 0.7, "reasoning": "llm"}
    with patch.object(d, "get_settings", return_value=_settings()):
        with patch.object(d, "tier3_llm_detection", new=AsyncMock(return_value=fake)) as mock_t3:
            result = await d.run_detection(bot, utterances)
    assert result == fake
    mock_t3.assert_awaited_once()


# ---------------------------------------------------------------------------
# tier3_llm_detection — happy + failure paths (httpx mocked)
# ---------------------------------------------------------------------------


async def test_tier3_llm_detection_parses_result(fake_llm):
    """Through the gateway since phase 8. This site POSTed raw httpx to
    api.anthropic.com before that, which is why no Anthropic-surface test ever
    flagged it."""
    fake_llm.queue_text(
        '{"candidate_participant_id": 2, "confidence": 0.8, "reasoning": "r"}'
    )

    with patch.object(d, "get_settings", return_value=_settings()):
        result = await d.tier3_llm_detection(
            "Cand", [{"id": 2, "name": "Cand"}], {"2": "hello"}, llm=fake_llm
        )

    assert result["candidate_participant_id"] == 2
    assert result["confidence"] == 0.8
    assert fake_llm.calls[0]["model"] == "candidate-detect"


async def test_tier3_llm_detection_returns_none_on_an_empty_reply(fake_llm):
    """An empty completion parses to nothing and returns None, which the
    orchestrator reads as "this tier found no candidate" — identical to a
    confident negative. The distinct log line is the only thing separating them."""
    fake_llm.queue_text("")

    with patch.object(d, "get_settings", return_value=_settings()):
        result = await d.tier3_llm_detection(
            "Cand", [{"id": 2, "name": "Cand"}], {"2": "hello"}, llm=fake_llm
        )

    assert result is None


async def test_tier3_llm_detection_returns_none_on_exception():
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=RuntimeError("boom"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(d, "get_settings", return_value=_settings()):
        with patch.object(d.httpx, "AsyncClient", return_value=mock_client):
            result = await d.tier3_llm_detection("Cand", [{"id": 2, "name": "Cand"}], {"2": "hi"})
    assert result is None


# ---------------------------------------------------------------------------
# store_detection_result — persists + flushes the buffer
# ---------------------------------------------------------------------------


async def test_store_detection_result_writes_and_clears():
    update_q = AsyncMock()
    update_q.update = MagicMock(return_value=update_q)
    update_q.eq = MagicMock(return_value=update_q)
    update_q.execute_async = AsyncMock(return_value=MagicMock(data=[{}]))

    supabase = MagicMock()
    supabase.table = MagicMock(return_value=update_q)

    result = {"candidate_participant_id": 2, "confidence": 0.85, "reasoning": "r"}
    utterances = {"2": "spoke"}

    with patch.object(d, "get_supabase_admin_client", return_value=supabase):
        with patch.object(d, "clear_utterances") as mock_clear:
            await d.store_detection_result("bot-1", result, utterances)

    update_payload = update_q.update.call_args[0][0]
    assert update_payload["detected_candidate_participant_id"] == 2
    assert update_payload["detection_confidence"] == 0.85
    assert update_payload["detection_completed"] is True
    assert update_payload["participant_utterances"] == utterances
    mock_clear.assert_called_once_with("bot-1")


# ---------------------------------------------------------------------------
# check_retroactive_trigger
# ---------------------------------------------------------------------------


async def test_check_retroactive_trigger_fires_when_left_and_confident():
    bot = {"tracked_participants": [{"id": 2, "left_at": "2025-01-15T10:00:00Z"}]}
    result = {"candidate_participant_id": 2, "confidence": 0.95}
    with patch.object(d, "get_settings", return_value=_settings()):
        assert await d.check_retroactive_trigger(bot, result) is True


async def test_check_retroactive_trigger_no_fire_if_still_present():
    bot = {"tracked_participants": [{"id": 2, "left_at": None}]}
    result = {"candidate_participant_id": 2, "confidence": 0.95}
    with patch.object(d, "get_settings", return_value=_settings()):
        assert await d.check_retroactive_trigger(bot, result) is False


async def test_check_retroactive_trigger_no_fire_below_confidence():
    bot = {"tracked_participants": [{"id": 2, "left_at": "2025-01-15T10:00:00Z"}]}
    result = {"candidate_participant_id": 2, "confidence": 0.5}
    with patch.object(d, "get_settings", return_value=_settings()):
        assert await d.check_retroactive_trigger(bot, result) is False
