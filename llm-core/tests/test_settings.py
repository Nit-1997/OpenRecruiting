import pytest

from llm_core.settings import get_settings

ENV_NAMES = (
    "LLM_GATEWAY_URL",
    "LITELLM_MASTER_KEY",
    "LLM_FORCE_JSON_TOOLS",
    "LLM_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def _drop_cached_settings():
    """Stop a value built from monkeypatched env leaking into other modules."""
    yield
    get_settings.cache_clear()


def test_defaults_when_nothing_is_set(monkeypatch):
    get_settings.cache_clear()
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert settings.gateway_url == "http://litellm:4000"
    assert settings.api_key == ""
    assert settings.force_json_tools == frozenset()
    assert settings.timeout_seconds == 60.0


def test_gateway_url_strips_trailing_slashes(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.internal:4000/")

    assert get_settings().gateway_url == "http://gateway.internal:4000"

    get_settings.cache_clear()
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.internal:4000///")

    assert get_settings().gateway_url == "http://gateway.internal:4000"


def test_force_json_tools_splits_and_drops_blanks(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_FORCE_JSON_TOOLS", " intake-jd-local , ,smoke-local,  ,gemma-local ")

    assert get_settings().force_json_tools == frozenset(
        {"intake-jd-local", "smoke-local", "gemma-local"}
    )


def test_force_json_tools_empty_string_yields_empty_set(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_FORCE_JSON_TOOLS", "  ,  , ")

    assert get_settings().force_json_tools == frozenset()


def test_timeout_seconds_is_converted_to_float(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")

    settings = get_settings()

    assert settings.timeout_seconds == 12.5
    assert isinstance(settings.timeout_seconds, float)


def test_api_key_is_read_from_master_key(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LITELLM_MASTER_KEY", "test-master-key")

    assert get_settings().api_key == "test-master-key"
