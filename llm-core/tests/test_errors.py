from llm_core.errors import LLMError, ToolEmulationError


def test_empty_message_never_renders_bare():
    assert (
        str(LLMError("", alias="intake-jd", status=503, provider="openai"))
        == "unknown LLM failure alias=intake-jd status=503 provider=openai"
    )


def test_plain_message_passes_through():
    assert str(LLMError("boom")) == "boom"


def test_tool_emulation_error_is_an_llm_error():
    err = ToolEmulationError("bad json", alias="intake-jd")

    assert isinstance(err, LLMError)
