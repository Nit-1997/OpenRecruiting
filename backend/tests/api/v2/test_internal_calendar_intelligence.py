def test_cal_intel_schedule_rejects_without_secret(unauthed_client):
    resp = unauthed_client.post("/api/v2/internal/calendar-intelligence/schedule", json={})
    assert resp.status_code in (403, 422)


def test_cal_intel_backfill_rejects_without_secret(unauthed_client):
    resp = unauthed_client.post("/api/v2/internal/calendar-intelligence/backfill", json={})
    assert resp.status_code in (403, 422)
