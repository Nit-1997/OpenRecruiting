import pytest
from app.integrations.ats.passthrough.ashby.scorecards import AshbyScorecardsAdapter


class _FakeTransport:
    def __init__(self, response): self._response = response
    async def passthrough(self, integration_id, method, path, body=None):
        assert path == "/applicationFeedback.list"
        assert body == {"applicationId": "app-1"}
        return self._response


def _real_item() -> dict:
    """Mirrors the live applicationFeedback.list item shape (verified 2026-06-12)."""
    return {
        "id": "d7515f01-aaaa-bbbb-cccc-000000000001",
        "formDefinition": {"sections": [{"fields": [
            {"field": {"type": "ValueSelect", "path": "overall_recommendation",
                       "title": "Overall Recommendation",
                       "selectableValues": [
                           {"label": "4 - Strong Yes", "value": "4"},
                           {"label": "3 - Yes", "value": "3"},
                           {"label": "2 - No", "value": "2"},
                           {"label": "1 - Strong No", "value": "1"},
                       ]}},
            {"field": {"type": "Boolean", "path": "willing_to_relocate",
                       "title": "Willing to relocate?"}},
            {"field": {"type": "ValueSelect", "path": "compensation_expectation",
                       "title": "Compensation Expectation"}},
        ]}]},
        "feedbackFormDefinitionId": "fb32498a-1111-2222-3333-444444444444",
        "applicationId": "47923ac0-5555-6666-7777-888888888888",
        "submittedValues": {
            "overall_recommendation": "4",
            "willing_to_relocate": True,
            "compensation_expectation": "below_band",
        },
        "submittedByUser": {
            "id": "9569ba1d-9999-aaaa-bbbb-cccccccccccc",
            "firstName": "Willie", "lastName": "Guerrero",
            "email": "willie@example.com",
        },
        "interviewId": "659373ef-dddd-eeee-ffff-000000000000",
        "interviewEventId": "8dbfbce4-1234-5678-9abc-def012345678",
        "submittedAt": "2026-06-12T00:00:00.000Z",
    }


@pytest.mark.asyncio
async def test_fetch_scorecards_maps_real_feedback_item():
    adapter = AshbyScorecardsAdapter(_FakeTransport({"results": [_real_item()]}), "iid-1")
    cards = await adapter.fetch_scorecards("app-1", "cand-1")

    assert len(cards) == 1
    c = cards[0]
    assert c.id == "d7515f01-aaaa-bbbb-cccc-000000000001"
    # overall recommendation is the raw string value at path overall_recommendation
    assert c.recommendation == "4"
    # interviewer comes from submittedByUser, not userId
    assert c.interviewer_id == "9569ba1d-9999-aaaa-bbbb-cccccccccccc"
    assert c.interviewer_name == "Willie Guerrero"
    # interview_id is interviewEventId
    assert c.interview_id == "8dbfbce4-1234-5678-9abc-def012345678"
    # non-overall submittedValues become attributes, titled from formDefinition
    by_name = {a.name: a for a in c.attributes}
    assert "Overall Recommendation" not in by_name  # routed to recommendation
    assert by_name["Compensation Expectation"].rating == "below_band"
    assert by_name["Compensation Expectation"].type == "ValueSelect"
    assert by_name["Willing to relocate?"].rating is True
    assert by_name["Willing to relocate?"].type == "Boolean"


@pytest.mark.asyncio
async def test_fetch_scorecards_empty():
    adapter = AshbyScorecardsAdapter(_FakeTransport({"results": []}), "iid-1")
    assert await adapter.fetch_scorecards("app-1", "cand-1") == []


@pytest.mark.asyncio
async def test_fetch_scorecards_non_list_results_guard():
    # results not a list (or absent) → no scorecards, no crash
    adapter = AshbyScorecardsAdapter(_FakeTransport({"results": None}), "iid-1")
    assert await adapter.fetch_scorecards("app-1", "cand-1") == []
    adapter = AshbyScorecardsAdapter(_FakeTransport({}), "iid-1")
    assert await adapter.fetch_scorecards("app-1", "cand-1") == []


@pytest.mark.asyncio
async def test_fetch_scorecards_skips_non_dict_items():
    item = _real_item()
    adapter = AshbyScorecardsAdapter(_FakeTransport({"results": [None, item]}), "iid-1")
    cards = await adapter.fetch_scorecards("app-1", "cand-1")
    assert len(cards) == 1
    assert cards[0].id == item["id"]


@pytest.mark.asyncio
async def test_fetch_scorecards_overall_only_no_attributes():
    item = {
        "id": "fb-3",
        "formDefinition": {"sections": [{"fields": [
            {"field": {"type": "ValueSelect", "path": "overall_recommendation",
                       "title": "Overall Recommendation"}},
        ]}]},
        "submittedValues": {"overall_recommendation": "3"},
        "submittedByUser": {"id": "u-3", "firstName": "Ada", "lastName": "Lovelace"},
        "interviewEventId": "iv-3",
        "submittedAt": "2026-06-12T00:00:00.000Z",
    }
    adapter = AshbyScorecardsAdapter(_FakeTransport({"results": [item]}), "iid-1")
    cards = await adapter.fetch_scorecards("app-1", "cand-1")
    assert cards[0].recommendation == "3"
    assert cards[0].attributes == []
