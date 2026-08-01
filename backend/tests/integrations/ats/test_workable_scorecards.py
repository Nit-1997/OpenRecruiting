import pytest
from app.integrations.ats.passthrough.workable.scorecards import WorkableScorecardsAdapter


class _FakeTransport:
    def __init__(self, resp): self._resp = resp
    async def passthrough(self, integration_id, method, path, body=None):
        assert path == "/candidates/c1/activities"; return self._resp


@pytest.mark.asyncio
async def test_fetch_scorecards_filters_rating_activities():
    resp = {"activities": [
        {"action": "comment", "body": "x"},
        {"id": "r1", "action": "rating", "created_at": "2026-03-03T00:00:00Z",
         "member": {"id": "m1", "name": "Alexia Middleton"}, "body": "Good",
         "rating": {"score": "positive", "scale": "thumbs", "grade": 1}},
    ]}
    cards = await WorkableScorecardsAdapter(_FakeTransport(resp), "iid").fetch_scorecards("app", "c1")
    assert len(cards) == 1
    assert cards[0].interviewer_name == "Alexia Middleton"
    assert cards[0].recommendation == "positive"


@pytest.mark.asyncio
async def test_fetch_scorecards_empty():
    cards = await WorkableScorecardsAdapter(_FakeTransport({"activities": []}), "iid").fetch_scorecards("app", "c1")
    assert cards == []
