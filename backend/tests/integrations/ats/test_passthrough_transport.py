import json

from app.integrations.ats.unified_knit.transport import KnitTransport


async def test_passthrough_unwraps_stringified_body(monkeypatch):
    t = KnitTransport(api_key="k", base_url="https://api.getknit.dev/v1.0")

    captured = {}
    stringified_body = json.dumps({"results": {"id": "c1"}})

    async def fake_request(method, path, *, integration_id=None, params=None, json=None):
        captured.update(method=method, path=path, integration_id=integration_id, json=json)
        return {"success": True, "data": {"response": {"body": stringified_body}}}

    monkeypatch.setattr(t, "request", fake_request)

    out = await t.passthrough("iid-1", "POST", "/candidate.info", {"id": "c1"})

    assert out == {"results": {"id": "c1"}}
    assert captured["path"] == "/passthrough"
    assert captured["integration_id"] == "iid-1"
    assert captured["json"] == {"method": "POST", "path": "/candidate.info", "body": {"id": "c1"}}


async def test_passthrough_invalid_json_body_returns_empty_dict(monkeypatch):
    t = KnitTransport(api_key="k", base_url="https://api.getknit.dev/v1.0")

    async def fake_request(method, path, *, integration_id=None, params=None, json=None):
        return {"data": {"response": {"body": "<<not json>>"}}}

    monkeypatch.setattr(t, "request", fake_request)

    out = await t.passthrough("iid-1", "POST", "/candidate.info", {"id": "c1"})

    assert out == {}


async def test_passthrough_non_dict_body_coerces_to_empty_dict(monkeypatch):
    t = KnitTransport(api_key="k", base_url="https://api.getknit.dev/v1.0")

    async def fake_request(method, path, *, integration_id=None, params=None, json=None):
        return {"data": {"response": {"body": None}}}

    monkeypatch.setattr(t, "request", fake_request)

    out = await t.passthrough("iid-1", "POST", "/candidate.info", body=None)

    assert out == {}
