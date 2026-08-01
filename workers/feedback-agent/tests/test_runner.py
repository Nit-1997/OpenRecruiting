from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock
import importlib.util
import sys

import pytest


# Bypass src/__init__.py (which imports heavy services with native deps).
# The runner has no transitive deps; load it from its file path directly.
if "src" not in sys.modules:
    sys.modules["src"] = ModuleType("src")

_runner_path = Path(__file__).resolve().parents[1] / "src" / "runner.py"
_spec = importlib.util.spec_from_file_location("src.runner", _runner_path)
_runner_module = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_runner_module)
sys.modules["src.runner"] = _runner_module

run_pipeline_for_inputs = _runner_module.run_pipeline_for_inputs


@pytest.mark.asyncio
async def test_run_pipeline_routes_scorecard_path():
    processor = AsyncMock()
    processor.process_from_scorecard.return_value = {"complete_result": {}, "evidence_result": {}, "judge_result": {}, "summary_result": {}}

    result = await run_pipeline_for_inputs(
        feedback_source={"source": "scorecard", "scorecard_transcript": "X", "has_interview_transcript": True},
        questions=[{"id": "q1", "question_number": 1, "heading": "H", "description": "D"}],
        role_context={"role": "PM"},
        transcript={"segments": [{"a": 1}], "feedback_transcript": "", "feedback_start_timestamp": None},
        processor=processor,
    )

    processor.process_from_scorecard.assert_awaited_once_with(
        scorecard_text="X",
        questions=[{"id": "q1", "question_number": 1, "heading": "H", "description": "D"}],
        role_context={"role": "PM"},
        interview_segments=[{"a": 1}],
    )
    processor.process_from_segments.assert_not_called()
    assert "complete_result" in result


@pytest.mark.asyncio
async def test_run_pipeline_routes_bot_path():
    processor = AsyncMock()
    processor.process_from_segments.return_value = {"complete_result": {}, "evidence_result": {}, "judge_result": {}, "summary_result": {}}

    await run_pipeline_for_inputs(
        feedback_source={"source": "bot"},
        questions=[{"id": "q1", "question_number": 1, "heading": "H", "description": "D"}],
        role_context={"role": "PM"},
        transcript={"segments": [{"a": 1}], "feedback_transcript": "raw", "feedback_start_timestamp": 42.0},
        processor=processor,
    )

    processor.process_from_segments.assert_awaited_once_with(
        segments=[{"a": 1}],
        feedback_start_timestamp=42.0,
        questions=[{"id": "q1", "question_number": 1, "heading": "H", "description": "D"}],
        role_context={"role": "PM"},
    )
    processor.process_from_scorecard.assert_not_called()


@pytest.mark.asyncio
async def test_run_pipeline_scorecard_without_interview_transcript_passes_none():
    processor = AsyncMock()
    processor.process_from_scorecard.return_value = {}

    await run_pipeline_for_inputs(
        feedback_source={"source": "scorecard", "scorecard_transcript": "X", "has_interview_transcript": False},
        questions=[],
        role_context={},
        transcript={"segments": [{"a": 1}], "feedback_transcript": "", "feedback_start_timestamp": None},
        processor=processor,
    )

    call = processor.process_from_scorecard.await_args
    assert call.kwargs["interview_segments"] is None


@pytest.mark.asyncio
async def test_run_pipeline_scorecard_with_empty_segments_passes_none():
    """has_interview_transcript=True but segments are empty: pass None, not []."""
    processor = AsyncMock()
    processor.process_from_scorecard.return_value = {}

    await run_pipeline_for_inputs(
        feedback_source={"source": "scorecard", "scorecard_transcript": "X", "has_interview_transcript": True},
        questions=[],
        role_context={},
        transcript={"segments": [], "feedback_transcript": "", "feedback_start_timestamp": None},
        processor=processor,
    )

    call = processor.process_from_scorecard.await_args
    assert call.kwargs["interview_segments"] is None
