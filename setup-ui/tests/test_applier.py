"""The applier is what makes a saved setting actually take effect.

Every test here exists because the alternative — restart — looked like it
worked and did not. A save that silently applies nothing is the failure this
whole module was written to remove.
"""

import asyncio
import json

import pytest

from app.applier import Applier, ApplyError


@pytest.fixture
def applier(tmp_path):
    return Applier(tmp_path)


def _respond(applier, tmp_path, ok=True, detail="recreated"):
    """Play the sidecar: consume the request, write a matching result."""
    async def run():
        for _ in range(60):
            req = tmp_path / "apply-request.json"
            if req.exists():
                body = json.loads(req.read_text())
                req.unlink()
                (tmp_path / "apply-result.json").write_text(json.dumps(
                    {"id": body["id"], "ok": ok, "detail": detail,
                     "services": " ".join(body["services"])}))
                return
            await asyncio.sleep(0.05)
    return run()


@pytest.mark.asyncio
async def test_a_recreate_request_round_trips(applier, tmp_path):
    result, _ = await asyncio.gather(applier.recreate(["backend"]), _respond(applier, tmp_path))

    assert result["ok"] is True
    assert result["services"] == "backend"


@pytest.mark.asyncio
async def test_the_request_names_exactly_the_services_asked_for(applier, tmp_path):
    async def capture():
        for _ in range(60):
            req = tmp_path / "apply-request.json"
            if req.exists():
                body = json.loads(req.read_text())
                req.unlink()
                (tmp_path / "apply-result.json").write_text(json.dumps(
                    {"id": body["id"], "ok": True, "detail": "", "services": ""}))
                return body["services"]
            await asyncio.sleep(0.05)
        return None

    _, services = await asyncio.gather(
        applier.recreate(["backend", "voice-agent"]), capture()
    )
    assert services == ["backend", "voice-agent"]


@pytest.mark.asyncio
async def test_a_failure_is_returned_not_raised(applier, tmp_path):
    """A compose failure must reach the UI as a result the user can read, not
    an exception that hides which service broke."""
    result, _ = await asyncio.gather(
        applier.recreate(["backend"]),
        _respond(applier, tmp_path, ok=False, detail="no such image"),
    )

    assert result["ok"] is False
    assert "no such image" in result["detail"]


@pytest.mark.asyncio
async def test_a_stale_result_from_an_earlier_request_is_ignored(applier, tmp_path):
    """Two saves in quick succession must not let the first one's result be
    reported as the second's — that would show success for work that never ran."""
    (tmp_path / "apply-result.json").write_text(json.dumps(
        {"id": "an-older-request", "ok": True, "detail": "stale", "services": "x"}))

    result, _ = await asyncio.gather(
        applier.recreate(["backend"]), _respond(applier, tmp_path, detail="fresh")
    )

    assert result["detail"] == "fresh"


@pytest.mark.asyncio
async def test_an_empty_service_list_is_a_no_op(applier):
    result = await applier.recreate([])

    assert result["ok"] is True
    assert (result["services"], result["detail"]) == ("", "nothing to recreate")


@pytest.mark.asyncio
async def test_a_missing_sidecar_raises_with_the_manual_command(applier, tmp_path):
    """Silently skipping the recreate would reproduce the original bug: saved,
    reported fine, not running."""
    missing = Applier(tmp_path / "not-mounted")

    with pytest.raises(ApplyError, match="docker compose up -d backend"):
        await missing.recreate(["backend"])


@pytest.mark.asyncio
async def test_a_silent_sidecar_times_out_rather_than_hanging(applier, monkeypatch):
    import app.applier as module

    monkeypatch.setattr(module, "_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(module, "_POLL_SECONDS", 0.05)

    with pytest.raises(ApplyError, match="did not respond"):
        await applier.recreate(["backend"])
