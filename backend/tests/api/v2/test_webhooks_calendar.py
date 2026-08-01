def test_calendar_event_is_queued_not_ignored(unauthed_client, monkeypatch):
    import app.workers.calendar_intelligence_worker as worker
    async def fake_enqueue(event_type, data):
        return {"calendar_id": "cal_1", "hint_dt": None}
    monkeypatch.setattr(worker, "enqueue_calendar_sync_hint", fake_enqueue)
    resp = unauthed_client.post(
        "/api/v2/webhooks/recall/bot-status",
        json={"event": "calendar.sync_events", "data": {"calendar_id": "cal_1"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    assert body.get("reason") != "calendar_owned_by_v1"
