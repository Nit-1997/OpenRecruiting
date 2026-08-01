"""Extractor with a fake Anthropic client — no live API. Asserts the tool output
maps into ResumeProfile and that any failure degrades to a minimal profile."""

from app.services.ats_enrichment.profile_models import ResumeProfile
from app.services.ats_enrichment.signal_extractor import extract_resume_profile


class _Block:
    def __init__(self, tool_input):
        self.type = "tool_use"
        self.name = "emit_candidate_profile"
        self.input = tool_input


class _Msg:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, tool_input=None, raise_exc=None):
        self._input = tool_input
        self._raise = raise_exc

    async def create(self, **_kwargs):
        if self._raise is not None:
            raise self._raise
        return _Msg([_Block(self._input or {})])


class _FakeClient:
    def __init__(self, tool_input=None, raise_exc=None):
        self.messages = _FakeMessages(tool_input, raise_exc)


async def test_builds_profile_from_tool_output():
    canned = {
        "summary": "Senior FP&A leader",
        "total_experience_years": 12,
        "seniority": "senior",
        "skills": ["FP&A", "SQL"],
        "domains": ["Corporate Finance"],
        "work_history": [{"title": "Director", "company": "Acme", "is_current": True}],
    }
    prof = await extract_resume_profile(
        "resume text", client=_FakeClient(tool_input=canned), model="claude-sonnet-4-6"
    )
    assert prof.summary == "Senior FP&A leader"
    assert prof.total_experience_years == 12
    assert prof.skills == ["FP&A", "SQL"]
    assert prof.work_history[0].company == "Acme"


async def test_fail_soft_on_llm_error_keeps_raw_summary():
    prof = await extract_resume_profile(
        "raw resume text here",
        client=_FakeClient(raise_exc=RuntimeError("api down")),
        model="m",
    )
    assert prof.summary == "raw resume text here"
    assert prof.skills == []


async def test_empty_text_skips_llm():
    # raise_exc would fire if the client were called — proves we short-circuit
    prof = await extract_resume_profile(
        "   ", client=_FakeClient(raise_exc=AssertionError("must not call")), model="m"
    )
    assert prof == ResumeProfile()
