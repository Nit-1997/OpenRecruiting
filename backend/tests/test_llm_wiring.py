"""Guards the two things every phase-2 task assumes.

1. llm-core is installed in the TEST image, so `import llm_core` resolves and the
   `fake_llm` fixture exists. backend/Dockerfile installs it; Dockerfile.test was
   missed, and the symptom is a collection error, not a readable failure.
2. The backend has exactly one dependency-injectable handle on the gateway client,
   so router tests keep using app.dependency_overrides.

The third test is the migration's tripwire: llm-core rejects Anthropic-shaped tool
specs from the FAKE as well as the real client, so a forgotten
input_schema -> parameters translation fails in this suite rather than in
production. If that ever stops being true, every remaining task loses its safety
net and this test says so first.
"""

import llm_core
import pytest
from llm_core.errors import ToolEmulationError
from llm_core.fake import FakeLLM

from app.dependencies import get_llm_client


def test_fake_llm_fixture_is_registered(fake_llm):
    assert isinstance(fake_llm, FakeLLM)


def test_get_llm_client_returns_the_llm_core_singleton():
    assert get_llm_client() is llm_core.get_client()


async def test_fake_llm_rejects_an_anthropic_shaped_tool(fake_llm):
    with pytest.raises(ToolEmulationError) as exc:
        await fake_llm.complete(
            model="intake-jd",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "emit_job_description", "input_schema": {"type": "object"}}],
        )

    assert "input_schema" in str(exc.value)
