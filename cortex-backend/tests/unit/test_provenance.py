from datetime import datetime, timezone
from src.sync.provenance import Provenance, attach_provenance_to_attributes


def test_provenance_attach_to_empty_attrs():
    prov = Provenance(
        source_event_type="feedback_debrief_available",
        source_id="cr-uuid",
        ingested_at=datetime(2026, 5, 9, 14, 0, 0, tzinfo=timezone.utc),
        event_pk="ev-uuid",
    )
    out = attach_provenance_to_attributes({}, prov)
    assert out["_source_event_type"] == "feedback_debrief_available"
    assert out["_source_id"] == "cr-uuid"
    assert out["_ingested_at"] == "2026-05-09T14:00:00+00:00"
    assert out["_event_pk"] == "ev-uuid"


def test_provenance_preserves_existing_attrs():
    prov = Provenance(
        source_event_type="x",
        source_id="y",
        ingested_at=datetime(2026, 5, 9, tzinfo=timezone.utc),
        event_pk="z",
    )
    out = attach_provenance_to_attributes({"weight": 0.8, "evidence": "..."}, prov)
    assert out["weight"] == 0.8
    assert out["evidence"] == "..."
    assert out["_source_event_type"] == "x"


def test_provenance_does_not_mutate_input():
    prov = Provenance(
        source_event_type="x",
        source_id="y",
        ingested_at=datetime(2026, 5, 9, tzinfo=timezone.utc),
        event_pk="z",
    )
    original = {"a": 1}
    out = attach_provenance_to_attributes(original, prov)
    assert "a" in original and len(original) == 1
    assert out is not original
