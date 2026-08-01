import pytest
from app.services import intake_call_service as ics_module
from app.services.intake_call_service import IntakeCallService


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def is_null(self, *a, **k): return self
    async def execute_async(self): return _FakeResult(self._rows)


class _FakeSupabase:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name): return _FakeTable(self._rows)


class _FakeGcal:
    async def get_connection(self, profile_id):
        return {"profile_id": profile_id}

    async def create_calendar_event(self, **kwargs):
        self.last_kwargs = kwargs
        return {"event_id": "evt_1", "html_link": "https://cal/evt_1"}


@pytest.mark.asyncio
async def test_start_intake_call_uses_v2_hub_url(monkeypatch):
    fake_gcal = _FakeGcal()
    monkeypatch.setattr(ics_module, "get_supabase_admin_client",
                        lambda: _FakeSupabase([{"id": "11111111-1111-1111-1111-111111111111", "role_title": "Engineer"}]))
    monkeypatch.setattr(ics_module, "get_google_calendar_service", lambda: fake_gcal)

    class _S:
        APP_URL = "https://app-v2.test"
    monkeypatch.setattr(ics_module, "get_settings", lambda: _S())

    svc = IntakeCallService()
    result = await svc.start_intake_call(
        profile_id="p1", org_id="o1",
        requisition_id="11111111-1111-1111-1111-111111111111",
    )
    assert result["intake_call_url"] == "https://app-v2.test/intake?requisition_id=11111111-1111-1111-1111-111111111111"
    assert result["calendar_event_link"] == "https://cal/evt_1"
    assert fake_gcal.last_kwargs["location"] == result["intake_call_url"]
