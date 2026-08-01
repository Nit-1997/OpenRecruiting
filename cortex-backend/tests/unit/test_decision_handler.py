import pytest

from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_hired_produces_applied_to_and_hired_by(decision_handler):
    payload = load_fixture("decision_packet_hired.json")
    triplets = decision_handler.build_triplets_from_payload(payload, "org-001")

    rels = {t.relation for t in triplets}
    assert rels == {"APPLIED_TO", "HIRED_BY"}
    assert all(t.source_name == "Alice Johnson" for t in triplets)
    assert all(t.target_name == "Senior Backend Engineer" for t in triplets)


@pytest.mark.asyncio
async def test_withdrawn_produces_applied_to_and_withdrew_from(decision_handler):
    payload = load_fixture("decision_packet_withdrawn.json")
    triplets = decision_handler.build_triplets_from_payload(payload, "org-001")

    rels = {t.relation for t in triplets}
    assert rels == {"APPLIED_TO", "WITHDREW_FROM"}
    assert all(t.source_name == "Dave Wilson" for t in triplets)


@pytest.mark.asyncio
async def test_rejected_produces_applied_to_and_rejected_by(decision_handler):
    payload = {
        "candidate": {
            "id": "cand-005",
            "name": "Eve Chen",
            "organization_id": "org-001",
            "status": "rejected"
        },
        "requisition": {
            "id": "req-001",
            "role_title": "Senior Backend Engineer",
            "organization_id": "org-001",
            "status": "active"
        }
    }
    triplets = decision_handler.build_triplets_from_payload(payload, "org-001")

    rels = {t.relation for t in triplets}
    assert rels == {"APPLIED_TO", "REJECTED_BY"}


@pytest.mark.asyncio
async def test_active_produces_applied_to_only(decision_handler):
    # An undecided (active) candidate is still in the pipeline — APPLIED_TO is the
    # baseline edge, with no outcome edge yet.
    payload = {
        "candidate": {
            "id": "cand-006",
            "name": "Frank Lee",
            "organization_id": "org-001",
            "status": "active"
        },
        "requisition": {
            "id": "req-001",
            "role_title": "Senior Backend Engineer",
            "organization_id": "org-001"
        }
    }
    triplets = decision_handler.build_triplets_from_payload(payload, "org-001")
    assert len(triplets) == 1
    assert triplets[0].relation == "APPLIED_TO"
    assert triplets[0].target_name == "Senior Backend Engineer"
