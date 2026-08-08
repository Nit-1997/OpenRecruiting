"""The `fake_llm` fixture must arrive through the pytest11 entry point.

This module deliberately never imports FakeLLM or llm_core.pytest_plugin. If the
entry point in pyproject.toml is missing, misspelled, or the package was
installed without it, every test here errors with "fixture 'fake_llm' not found"
rather than quietly falling back to something a conftest provided. That is the
whole point: services migrating onto llm-core get the fixture by installing the
package, and nothing else.
"""

from importlib.metadata import entry_points


def test_the_pytest11_entry_point_is_registered():
    registered = {
        (ep.name, ep.value) for ep in entry_points(group="pytest11") if ep.name == "llm_core"
    }

    assert registered == {("llm_core", "llm_core.pytest_plugin")}


def test_fixture_is_available_without_importing_anything(fake_llm):
    assert type(fake_llm).__name__ == "FakeLLM"
    assert fake_llm.calls == []


async def test_fixture_is_usable_end_to_end(fake_llm):
    fake_llm.queue_text("hello")

    reply = await fake_llm.complete(model="intake-jd", messages=[{"role": "user", "content": "hi"}])

    assert reply.text == "hello"
    assert fake_llm.calls[0]["model"] == "intake-jd"


_seen: list[int] = []


def test_fixture_hands_out_a_fresh_instance_first(fake_llm):
    _seen.append(id(fake_llm))
    fake_llm.queue_text("only for this test")


def test_fixture_hands_out_a_fresh_instance_second(fake_llm):
    """A shared instance would leak a queue between tests and make failures
    depend on test order, which is the classic way a fixture like this rots."""
    _seen.append(id(fake_llm))

    assert len(_seen) == 2 and _seen[0] != _seen[1]
    assert fake_llm.calls == []
    assert fake_llm._queue == []
