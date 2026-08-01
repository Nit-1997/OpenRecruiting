from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Provenance:
    source_event_type: str
    source_id: str
    ingested_at: datetime
    event_pk: str


def attach_provenance_to_attributes(attrs: dict, prov: Provenance) -> dict:
    out = dict(attrs)
    out["_source_event_type"] = prov.source_event_type
    out["_source_id"] = prov.source_id
    out["_ingested_at"] = prov.ingested_at.isoformat()
    out["_event_pk"] = prov.event_pk
    return out
