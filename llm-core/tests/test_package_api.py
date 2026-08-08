"""The package's public surface.

Five service migrations are written against `llm.complete()` / `llm.stream_turn()`,
so the module-level `llm` name is load-bearing. It must resolve lazily: binding a
client at import time would construct AsyncOpenAI and read gateway settings during
`import llm_core`, breaking test collection and any process that imports the
package without gateway env vars set.
"""

import os
import subprocess
import sys

import pytest

import llm_core
from llm_core import client as client_module


def test_llm_is_a_declared_export():
    assert "llm" in llm_core.__all__


def test_importing_the_package_constructs_nothing_and_needs_no_env_vars():
    probe = (
        "import llm_core\n"
        "import llm_core.client as c\n"
        "assert c._client is None, 'importing llm_core constructed a client'\n"
        "assert 'llm' in llm_core.__all__\n"
        "from llm_core import llm\n"
        "assert llm is not None\n"
        "print('ok')\n"
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LLM_", "LITELLM_", "OPENAI_"))
    }
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env
    )

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_llm_resolves_lazily_and_returns_one_stable_instance(monkeypatch):
    constructed = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            constructed.append(kwargs)

    monkeypatch.setattr(client_module, "LLMClient", FakeClient)
    monkeypatch.setattr(client_module, "_client", None)

    assert constructed == []

    first = llm_core.llm
    second = llm_core.llm

    assert isinstance(first, FakeClient)
    assert first is second
    assert len(constructed) == 1


def test_from_import_reaches_the_lazy_attribute(monkeypatch):
    class FakeClient:
        pass

    monkeypatch.setattr(client_module, "LLMClient", FakeClient)
    monkeypatch.setattr(client_module, "_client", None)

    from llm_core import llm

    assert isinstance(llm, FakeClient)
    assert llm is client_module.get_client()


def test_unknown_attributes_still_raise_attributeerror():
    with pytest.raises(AttributeError):
        llm_core.definitely_not_an_export
