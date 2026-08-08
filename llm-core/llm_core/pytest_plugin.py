"""Registered as a pytest11 entry point, so `fake_llm` is available to any test
suite in a process where llm-core is installed — no conftest import required.
"""

import pytest

from llm_core.fake import FakeLLM


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
