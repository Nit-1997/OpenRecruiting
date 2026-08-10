"""Extractor against llm-core's FakeLLM — no live API and no provider shapes.

Asserts the tool output maps into ResumeProfile and that every failure degrades
to a minimal profile carrying the raw text, never to a blank one.
"""

import pytest
import structlog
from llm_core.errors import LLMError

from app.services.ats_enrichment.profile_models import ResumeProfile
from app.services.ats_enrichment.signal_extractor import extract_resume_profile

pytestmark = pytest.mark.asyncio

FORCED = {"type": "function", "function": {"name": "emit_candidate_profile"}}


async def test_builds_profile_from_tool_output(fake_llm):
    canned = {
        "summary": "Senior FP&A leader",
        "total_experience_years": 12,
        "seniority": "senior",
        "skills": ["FP&A", "SQL"],
        "domains": ["Corporate Finance"],
        "work_history": [{"title": "Director", "company": "Acme", "is_current": True}],
    }
    fake_llm.queue_tool_call("emit_candidate_profile", canned)

    prof = await extract_resume_profile("resume text", llm=fake_llm, model="resume-extract")

    assert prof.summary == "Senior FP&A leader"
    assert prof.total_experience_years == 12
    assert prof.skills == ["FP&A", "SQL"]
    assert prof.work_history[0].company == "Acme"


async def test_fail_soft_on_llm_error_keeps_raw_summary(fake_llm):
    fake_llm.queue_error(LLMError("api down", alias="resume-extract", status=502))

    prof = await extract_resume_profile(
        "raw resume text here", llm=fake_llm, model="resume-extract"
    )

    assert prof.summary == "raw resume text here"
    assert prof.skills == []


async def test_empty_text_skips_llm(fake_llm):
    prof = await extract_resume_profile("   ", llm=fake_llm, model="resume-extract")

    assert prof == ResumeProfile()
    assert fake_llm.calls == []   # nothing queued, nothing called


async def test_a_prose_reply_keeps_the_resume_rather_than_blanking_it(fake_llm):
    """Defence in depth behind the forced tool.

    Every ResumeProfile field has a default, so model_validate({}) SUCCEEDS and
    returns a blank profile — the degraded reply would silently discard the
    resume instead of degrading to it. The required-property check is what stops
    that, so it is asserted on the value, not just on the log line.
    """
    fake_llm.queue_text("This resume looks fine to me.")

    with structlog.testing.capture_logs() as logs:
        prof = await extract_resume_profile(
            "raw resume body", llm=fake_llm, model="resume-extract"
        )

    assert prof.summary == "raw resume body"
    assert [e["event"] for e in logs] == ["resume_extract_no_usable_tool_arguments"]
    assert logs[0]["had_tool_call"] is False


async def test_a_truncated_tool_call_keeps_the_resume(fake_llm):
    """The 2500-token budget against the largest tool schema in the codebase.
    llm_core surfaces unparseable argument JSON as arguments={} on a ToolCall
    that exists and is named correctly, so tool_call_named cannot see it."""
    fake_llm.queue_tool_call("emit_candidate_profile", {})

    with structlog.testing.capture_logs() as logs:
        prof = await extract_resume_profile(
            "raw resume body", llm=fake_llm, model="resume-extract"
        )

    assert prof.summary == "raw resume body"
    assert [e["event"] for e in logs] == ["resume_extract_no_usable_tool_arguments"]
    assert logs[0]["had_tool_call"] is True


async def test_a_partial_extraction_is_still_a_real_profile(fake_llm):
    """Only `summary` is required by the schema. A profile carrying it and
    nothing else is a genuine result, not a degraded one."""
    fake_llm.queue_tool_call("emit_candidate_profile", {"summary": "Ops lead"})

    with structlog.testing.capture_logs() as logs:
        prof = await extract_resume_profile(
            "raw resume body", llm=fake_llm, model="resume-extract"
        )

    assert prof.summary == "Ops lead"
    assert logs == []


async def test_malformed_tool_output_keeps_the_models_summary(fake_llm):
    """A summary that arrived but a sibling field that will not validate: the
    extraction is partly usable, so the model's own summary wins over the raw
    text. This is the branch the required-property check must not swallow."""
    fake_llm.queue_tool_call(
        "emit_candidate_profile",
        {"summary": "Senior analyst", "work_history": "not a list"},
    )

    prof = await extract_resume_profile(
        "raw resume body", llm=fake_llm, model="resume-extract"
    )

    assert prof.summary == "Senior analyst"


async def test_sends_the_untrusted_resume_and_one_forced_openai_tool(fake_llm):
    fake_llm.queue_tool_call("emit_candidate_profile", {"summary": "ok"})

    await extract_resume_profile("SECRET RESUME", llm=fake_llm, model="resume-extract")

    call = fake_llm.calls[0]
    assert call["model"] == "resume-extract"
    assert call["max_tokens"] == 2500
    assert call["tool_choice"] == FORCED
    assert "<untrusted_resume>" in call["messages"][0]["content"]
    assert call["tools"][0]["type"] == "function"
    assert call["tools"][0]["function"]["name"] == "emit_candidate_profile"


async def test_no_resume_text_reaches_the_degraded_log_line(fake_llm):
    """Resumes carry personal data. A degraded-shape log describes the shape."""
    secret = "Jane Doe, jane@example.com, 555-0100"
    fake_llm.queue_text(secret)

    with structlog.testing.capture_logs() as logs:
        await extract_resume_profile(secret, llm=fake_llm, model="resume-extract")

    assert secret not in str(logs)
