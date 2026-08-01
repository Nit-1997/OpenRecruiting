"""Intake-scoped screening config routes (pre-publish).

The recruiter configures the screening agent on a plan round DURING intake,
before the round exists in the DB. `round_screening_configs` keys on a round's
DB id (only minted at publish), so these routes are RETURN-ONLY: the FE stores
the result inside the intake plan artifact
(`intake_sessions.interview_plan.rounds[].screening`), and publish materializes
it into the DB (see `intake_publish_service.publish`).

  POST /intake/sessions/{session_id}/screening/generate        → draft questions
  POST /intake/sessions/{session_id}/screening/persona/derive  → persona

Both routes are gated by `get_current_user_with_org` and org-scoped via
session → requisition → org (404 on any mismatch). The generator + reduce
service are constructed per-request so tests can seam-mock their methods.

These mirror the post-publish `screening.py` routes (`generate` / `persona/derive`)
but source the requisition from the SESSION instead of a {round_id}.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.core.exceptions import NotFoundError
from app.api.v2.schemas.screening import PersonaResponse, ScreeningQuestion
from app.api.v2.services.persona_reduce_service import PersonaReduceService
from app.api.v2.services.screening_config_service import ScreeningConfigService  # noqa: F401 — seam-mocked in tests
from app.api.v2.services.screening_question_generator import (
    ScreeningQuestionGenerator,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/intake/sessions/{session_id}/screening", tags=["v2/screening"]
)


# --- request / response schemas (intake-scoped) ---------------------------------


class IntakeGenerateScreeningRequest(BaseModel):
    """The round's context the FE has from the artifact (no round_id yet)."""

    round_name: str
    category: str
    skills: list[str] | None = None
    preferences: str | None = None


class IntakeScreeningQuestionsResponse(BaseModel):
    """Draft questions only — the FE stores these in the plan artifact."""

    questions: list[ScreeningQuestion] = []


class IntakePersonaResponse(PersonaResponse):
    """Persona for the FE to store in the artifact — carries the full snapshot
    (which publish later persists + attaches to the materialized round config)."""

    persona_snapshot: dict = {}


async def _load_session_for_org(
    supabase, session_id: UUID, org_id: str
) -> dict:
    """Fetch an intake_sessions row (+ its requisition) and verify it belongs to
    org_id. Raises NotFoundError on a missing session or cross-org requisition."""
    result = await (
        supabase.table("intake_sessions")
        .select(
            "id, requisition_id, status, "
            "requisitions(id, organization_id, deleted_at, role_title, "
            "experience_min_years, experience_max_years, job_description, "
            "must_have_skills, good_to_have_skills)"
        )
        .eq("id", str(session_id))
        .single()
        .execute_async()
    )
    if not result.data:
        raise NotFoundError("Intake session not found")
    req = result.data.get("requisitions") or {}
    if req.get("organization_id") != org_id or req.get("deleted_at") is not None:
        raise NotFoundError("Intake session not found")
    return result.data


def _build_role_context(req: dict) -> str:
    """Compose a free-text role-context block from the requisition for the LLM.

    Mirrors screening.py:_build_role_context so intake + post-publish generate
    feed the model the same role shape."""
    lines: list[str] = []
    title = req.get("role_title")
    if title:
        lines.append(f"Role: {title}")
    lo, hi = req.get("experience_min_years"), req.get("experience_max_years")
    if lo is not None or hi is not None:
        if lo is not None and hi is not None:
            lines.append(f"Experience: {lo}-{hi} years")
        else:
            lines.append(f"Experience: {lo if lo is not None else hi}+ years")
    skills = req.get("good_to_have_skills") or []
    if skills:
        lines.append("Nice-to-have skills: " + ", ".join(str(s) for s in skills))
    jd = (req.get("job_description") or "").strip()
    if jd:
        lines.append(f"\nJob description:\n{jd}")
    return "\n".join(lines)


async def _fetch_org_name(supabase, org_id: str) -> str:
    """Best-effort org display name for the Cortex persona reader. Falls back to
    "OpenRecruiting" — never blocks derive (mirrors screening.py:_fetch_org_name)."""
    result = await (
        supabase.table("organizations")
        .select("name")
        .eq("id", org_id)
        .single()
        .execute_async()
    )
    if result.data and result.data.get("name"):
        return result.data["name"]
    return "OpenRecruiting"


@router.post("/generate", response_model=IntakeScreeningQuestionsResponse)
async def generate_screening(
    session_id: UUID,
    body: IntakeGenerateScreeningRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> IntakeScreeningQuestionsResponse:
    """Generate draft screening questions for a plan round during intake.

    RETURN-ONLY: nothing is persisted. The FE stores these in the plan artifact;
    publish materializes them into round_screening_configs."""
    session = await _load_session_for_org(
        supabase, session_id, current.organization_id_str
    )
    req = session.get("requisitions") or {}

    role_context = _build_role_context(req)
    must_haves = req.get("must_have_skills") or []
    # Phase 2: populate from Cortex (gap analysis on the role). Empty for now.
    cortex_gaps: list[str] = []

    questions = await ScreeningQuestionGenerator().generate(
        role_context=role_context,
        must_haves=must_haves,
        cortex_gaps=cortex_gaps,
        preferences=body.preferences,
    )
    return IntakeScreeningQuestionsResponse(questions=questions)


@router.post("/persona/derive", response_model=IntakePersonaResponse)
async def derive_persona(
    session_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> IntakePersonaResponse:
    """REDUCE the org's real interviewer style into a per-role screening persona
    for a plan round during intake.

    RETURN-ONLY for the round config: there is NO round yet, so we do NOT call
    set_persona. derive() still persists a `personas` row (keyed by requisition)
    and returns the snapshot; the FE stores it in the artifact and publish
    attaches it to the materialized round config. Cold-start safe — derive never
    raises (returns a generic persona)."""
    session = await _load_session_for_org(
        supabase, session_id, current.organization_id_str
    )
    req = session.get("requisitions") or {}
    requisition_id = session.get("requisition_id")
    org_id = current.organization_id_str
    org_name = await _fetch_org_name(supabase, org_id)
    role_title = req.get("role_title") or ""

    derived = await PersonaReduceService(supabase).derive(
        requisition_id=str(requisition_id),
        org_id=org_id,
        org_name=org_name,
        role_title=role_title,
        created_by=str(current.user.id),
    )

    return IntakePersonaResponse(
        persona_id=derived["persona_id"],
        dimensions=derived["dimensions"],
        composed_text=derived["composed_text"],
        persona_snapshot=derived["persona_snapshot"],
    )
