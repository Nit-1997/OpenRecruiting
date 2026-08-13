"""Admin (staff) router group, ported from v1 `app/api/v1/admin/*`.

Each sub-router is lifted verbatim from v1 and mounted here under the `/admin`
prefix so paths mirror v1 exactly: v1 `/api/v1/admin/<group>` -> v2
`/api/v2/admin/<group>`. Auth is the existing `require_staff` dependency
in `app/dependencies.py` (identical to v1). This lets the admin UI migrate one
group at a time while v1 stays intact as a fallback.
"""

from fastapi import APIRouter

from app.api.v2.routers.admin import (
    assessment_templates,
    blog_posts,
    candidates,
    feedback_jobs,
    intake_jobs,
    organizations,
    requisitions,
    users,
)

router = APIRouter(prefix="/admin")
router.include_router(assessment_templates.router)
router.include_router(blog_posts.router)
router.include_router(candidates.router)
router.include_router(feedback_jobs.router)
router.include_router(intake_jobs.router)
router.include_router(organizations.router)
router.include_router(requisitions.router)
router.include_router(users.router)
