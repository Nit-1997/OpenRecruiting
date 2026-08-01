"""Pure wire→canonical mapping. No I/O — unit-tested against golden samples."""

from app.integrations.ats.core.models import (
    AtsDepartment,
    AtsJob,
    AtsOffice,
    AtsStage,
    AtsTeamMember,
)
from app.integrations.ats.unified_knit.apis.jobs.wire_models import KnitJob


def to_ats_job(wire: KnitJob) -> AtsJob:
    return AtsJob(
        id=wire.info.id,
        title=wire.info.title,
        status=wire.info.status,
        description=wire.info.description,
        created_at=wire.info.created_at,
        updated_at=wire.info.updated_at,
        info_url=wire.info.info_url,
        apply_url=wire.info.apply_url,
        departments=[
            AtsDepartment(id=d.id, name=d.name) for d in (wire.departments or [])
        ],
        offices=[
            AtsOffice(id=o.id, name=o.name, location=o.location)
            for o in (wire.offices or [])
        ],
        hiring_managers=[
            AtsTeamMember(id=m.id, email=m.email)
            for m in (wire.hiring_managers or [])
        ],
        recruiters=[
            AtsTeamMember(id=r.id, email=r.email) for r in (wire.recruiters or [])
        ],
        stages=[AtsStage(id=s.id, name=s.text) for s in (wire.stages or [])],
    )
