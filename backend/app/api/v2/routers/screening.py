"""
Recruiter-facing per-round screening config routes.

  POST /roles/{requisition_id}/rounds/{round_id}/screening/generate  → draft (not saved)
  GET  /roles/{requisition_id}/rounds/{round_id}/screening           → saved config
  PUT  /roles/{requisition_id}/rounds/{round_id}/screening           → save config
  POST /roles/{requisition_id}/rounds/{round_id}/screening/attach    → enable
  POST /roles/{requisition_id}/rounds/{round_id}/screening/detach    → disable

Every route is gated by `get_current_user_with_org` and verifies the round's
requisition belongs both to the caller's org AND to the {requisition_id} in the
path (404 on either mismatch). The generator + config service are constructed
per-request so tests can seam-mock their methods.
"""

import secrets
from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.api.v2.core.rpc import call_rpc
from app.api.v2.schemas.screening import (
    GenerateScreeningRequest,
    InviteRequest,
    PersonaResponse,
    SavePersonaRequest,
    ScreeningConfig,
    SelectPersonaRequest,
)
from app.api.v2.services.persona_library_service import PersonaLibraryService
from app.api.v2.services.persona_reduce_service import PersonaReduceService
from app.api.v2.services.screening_config_service import ScreeningConfigService
from app.api.v2.services.screening_question_generator import (
    ScreeningQuestionGenerator,
)
from intake_core.screening.persona import (
    Persona,
    PersonaDimension,
    compose_persona,
    persona_to_snapshot,
)
from app.logging_config import get_logger
from app.services.screening_invite_service import get_screening_invite_service

logger = get_logger(__name__)


router = APIRouter(prefix="/roles/{requisition_id}/rounds/{round_id}/screening", tags=["v2/screening"])


async def _load_round_for_org(
    supabase, requisition_id: UUID, round_id: UUID, org_id: str
) -> dict:
    """Fetch a round (+ its requisition) and verify it belongs to org_id and to
    the requisition_id in the path. Raises NotFoundError on any mismatch."""
    result = await (
        supabase.table("rounds")
        .select(
            "*, requisitions(id, organization_id, deleted_at, role_title, "
            "experience_min_years, experience_max_years, job_description, "
            "must_have_skills, good_to_have_skills)"
        )
        .eq("id", str(round_id))
        .is_null("deleted_at")
        .single()
        .execute_async()
    )
    if not result.data:
        raise NotFoundError("Round not found")
    if result.data.get("requisition_id") != str(requisition_id):
        raise NotFoundError("Round not found")
    req = result.data.get("requisitions") or {}
    if req.get("organization_id") != org_id or req.get("deleted_at") is not None:
        raise NotFoundError("Round not found")
    return result.data


def _build_role_context(req: dict) -> str:
    """Compose a free-text role-context block from the requisition for the LLM."""
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


@router.post("/generate", response_model=ScreeningConfig)
async def generate_screening(
    requisition_id: UUID,
    round_id: UUID,
    body: GenerateScreeningRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> ScreeningConfig:
    round_row = await _load_round_for_org(
        supabase, requisition_id, round_id, current.organization_id_str
    )
    req = round_row.get("requisitions") or {}

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

    # Draft only — NOT persisted. Recruiter edits, then PUTs to save.
    return ScreeningConfig(round_id=str(round_id), questions=questions)


@router.get("")
async def get_screening(
    requisition_id: UUID,
    round_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict | None:
    await _load_round_for_org(
        supabase, requisition_id, round_id, current.organization_id_str
    )
    return await ScreeningConfigService(supabase).get(str(round_id))


@router.put("")
async def save_screening(
    requisition_id: UUID,
    round_id: UUID,
    body: ScreeningConfig,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict | None:
    await _load_round_for_org(
        supabase, requisition_id, round_id, current.organization_id_str
    )
    # Path round_id is authoritative over whatever the body carries.
    body.round_id = str(round_id)
    service = ScreeningConfigService(supabase)
    await service.upsert(
        body,
        requisition_id=str(requisition_id),
        created_by=str(current.user.id),
    )
    return await service.get(str(round_id))


@router.post("/attach")
async def attach_screening(
    requisition_id: UUID,
    round_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict | None:
    await _load_round_for_org(
        supabase, requisition_id, round_id, current.organization_id_str
    )
    # Return the FULL saved config (mirrors PUT) so the panel keeps its
    # questions/voice/validity after toggling — set_enabled alone returns a thin
    # {round_id, enabled} that would wipe the panel's config on setConfig(result).
    service = ScreeningConfigService(supabase)
    await service.set_enabled(str(round_id), True)
    config = await service.get(str(round_id))
    if not config:
        # set_enabled updated 0 rows because no config exists yet. Don't return
        # null (the client's configFromWire would throw a cryptic TypeError) —
        # raise a clear domain error so the caller knows to save a config first.
        raise NotFoundError("Screening config not found — save it first")
    return config


@router.post("/detach")
async def detach_screening(
    requisition_id: UUID,
    round_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict | None:
    await _load_round_for_org(
        supabase, requisition_id, round_id, current.organization_id_str
    )
    service = ScreeningConfigService(supabase)
    await service.set_enabled(str(round_id), False)
    config = await service.get(str(round_id))
    if not config:
        raise NotFoundError("Screening config not found — save it first")
    return config


async def _fetch_org_name(supabase, org_id: str) -> str:
    """Best-effort org display name for the Cortex persona reader. Falls back to
    "OpenRecruiting" (mirrors mcp_oauth._load_user_org_context) — never blocks derive."""
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


# ============================================================================
# Persona — config-time interviewer style (derive from Cortex / recruiter-edit)
# ============================================================================


@router.post("/persona/derive", response_model=PersonaResponse)
async def derive_persona(
    requisition_id: UUID,
    round_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> PersonaResponse:
    """REDUCE the org's real interviewer style into a per-role screening persona
    and attach it to the round config so the live voice screen uses it.

    Cold-start safe: derive never raises (returns a generic persona). set_persona
    is a no-op if the round has no config yet — we still return the persona."""
    round_row = await _load_round_for_org(
        supabase, requisition_id, round_id, current.organization_id_str
    )
    req = round_row.get("requisitions") or {}
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

    await ScreeningConfigService(supabase).set_persona(
        str(round_id), derived["persona_id"], derived["persona_snapshot"]
    )

    return PersonaResponse(
        persona_id=derived["persona_id"],
        dimensions=derived["dimensions"],
        composed_text=derived["composed_text"],
    )


@router.put("/persona", response_model=PersonaResponse)
async def save_persona(
    requisition_id: UUID,
    round_id: UUID,
    body: SavePersonaRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> PersonaResponse:
    """Recruiter edits the rubric: recompose the persona text from the edited
    dimensions (compose_persona always re-appends guardrails), persist a new
    personas row, and attach it to the round config."""
    round_row = await _load_round_for_org(
        supabase, requisition_id, round_id, current.organization_id_str
    )
    req = round_row.get("requisitions") or {}

    dims = [
        PersonaDimension(
            key=d.key,
            value=d.value,
            confidence=d.confidence,
            source=d.source,
        )
        for d in body.dimensions
    ]
    composed_text = compose_persona(dims)
    snapshot = persona_to_snapshot(Persona(dimensions=dims, text=composed_text))

    persona_id = await PersonaReduceService(supabase).persist_persona(
        requisition_id=str(requisition_id),
        org_id=current.organization_id_str,
        role_title=req.get("role_title") or "",
        created_by=str(current.user.id),
        dimensions=snapshot["dimensions"],
        composed_text=composed_text,
    )

    await ScreeningConfigService(supabase).set_persona(
        str(round_id), persona_id, snapshot
    )

    return PersonaResponse(
        persona_id=persona_id,
        dimensions=snapshot["dimensions"],
        composed_text=composed_text,
    )


@router.get("/persona", response_model=PersonaResponse)
async def get_persona(
    requisition_id: UUID,
    round_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> PersonaResponse:
    """Return the round config's currently-attached persona snapshot, or empty."""
    await _load_round_for_org(
        supabase, requisition_id, round_id, current.organization_id_str
    )
    config = await ScreeningConfigService(supabase).get(str(round_id))
    if not config:
        return PersonaResponse()
    snapshot = config.get("persona_snapshot") or {}
    return PersonaResponse(
        persona_id=config.get("persona_id"),
        dimensions=snapshot.get("dimensions") or [],
        composed_text=snapshot.get("text") or "",
    )


@router.post("/persona/select", response_model=PersonaResponse)
async def select_persona(
    requisition_id: UUID,
    round_id: UUID,
    body: SelectPersonaRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> PersonaResponse:
    """Pick a saved org persona and attach it to this round's screening config.

    Loads the persona org-scoped (404 if missing or cross-org), builds the
    persona_snapshot from its stored dimensions + composed_text, and reuses
    ScreeningConfigService.set_persona — the same seam derive/edit use — so the
    live voice screen reads the chosen persona. No recompose: the saved
    composed_text is the source of truth."""
    await _load_round_for_org(
        supabase, requisition_id, round_id, current.organization_id_str
    )

    persona = await PersonaLibraryService(supabase).get(
        body.persona_id, org_id=current.organization_id_str
    )
    snapshot = PersonaLibraryService.snapshot_from_row(persona)

    await ScreeningConfigService(supabase).set_persona(
        str(round_id), persona["id"], snapshot
    )

    return PersonaResponse(
        persona_id=persona["id"],
        dimensions=snapshot["dimensions"],
        composed_text=snapshot["text"],
    )


async def _resolve_invite_emails(
    supabase, requisition_id: UUID, body: InviteRequest
) -> list[str]:
    """Resolve the set of candidate emails to invite.

    Explicit `emails` always wins. `scope='all_resume_passed'` falls back to the
    requisition's active (non-deleted) candidates.

    ASSUMPTION (documented): there is no resume-screen pass/fail status column on
    `candidates` (status is only active/hired/rejected/withdrawn — see
    02-interview-plan-requisition.sql). Until a resume-screen status lands, the
    'all_resume_passed' scope is interpreted as "all active candidates on this
    role". This is the explicitly-permitted simplification, not over-engineering
    a status filter that the schema can't yet express.
    """
    if body.emails:
        # De-dup, normalise, drop blanks. Preserve first-seen order.
        seen: set[str] = set()
        out: list[str] = []
        for raw in body.emails:
            email = (raw or "").strip().lower()
            if email and email not in seen:
                seen.add(email)
                out.append(email)
        return out

    if body.scope == "all_resume_passed":
        result = await (
            supabase.table("candidates")
            .select("email")
            .eq("requisition_id", str(requisition_id))
            .eq("status", "active")
            .is_null("deleted_at")
            .execute_async()
        )
        rows = result.data or []
        seen = set()
        out = []
        for row in rows:
            email = (row.get("email") or "").strip().lower()
            if email and email not in seen:
                seen.add(email)
                out.append(email)
        return out

    return []


@router.post("/invite")
async def invite_candidates(
    requisition_id: UUID,
    round_id: UUID,
    body: InviteRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    """Invite candidates to the round's screening interview.

    Each candidate gets an OTP-gated link valid for the round config's
    `validity_days`. Per email: one atomic RPC upserts the candidate + the
    screening candidate_round + the invite row (token minted here in Python so
    we can build the verify link), then we email the invite outside the
    transaction. Email failures are reported per-recipient and do not roll back
    the invite row (the link is already live).
    """
    round_row = await _load_round_for_org(
        supabase, requisition_id, round_id, current.organization_id_str
    )
    req = round_row.get("requisitions") or {}
    role_title = req.get("role_title")

    config = await ScreeningConfigService(supabase).get(str(round_id))
    if not config:
        raise ValidationError(
            "Screening is not configured for this round — save a config first"
        )
    validity_days = int(config.get("validity_days") or 7)

    emails = await _resolve_invite_emails(supabase, requisition_id, body)
    if not emails:
        raise ValidationError("No candidates to invite")

    invite_service = get_screening_invite_service()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=validity_days)

    invited = 0
    email_failures: list[str] = []
    for email in emails:
        token = secrets.token_urlsafe(32)
        payload = {
            "requisition_id": str(requisition_id),
            "round_id": str(round_id),
            "email": email,
            "created_by": str(current.user.id),
            "token": token,
            "expires_at": expires_at.isoformat(),
        }
        await call_rpc(supabase, "screening_create_invite", {"p": payload})
        invited += 1

        try:
            await invite_service.send_invite_email_for_token(
                email=email,
                token=token,
                role_title=role_title,
                candidate_name=None,
                validity_days=validity_days,
            )
        except Exception:
            # The invite row is persisted; only the email send failed. Surface
            # it per-recipient rather than failing the whole batch.
            logger.exception("screening invite email failed for %s", email)
            email_failures.append(email)

    logger.info(
        "screening.invites_created",
        extra={
            "requisition_id": str(requisition_id),
            "round_id": str(round_id),
            "invited": invited,
            "email_failures": len(email_failures),
        },
    )

    return {
        "invited": invited,
        "validity_days": validity_days,
        "expires_at": expires_at.isoformat(),
        "email_failures": email_failures,
    }


# ============================================================================
# Per-candidate-round invite — "schedule" a OpenRecruiting-hosted round = send the link.
#
# Distinct from the bulk /roles/.../invite above (which creates candidate +
# round + invite): here the candidate_round ALREADY exists (a pipeline candidate
# with rounds). Scheduling a OpenRecruiting round means sending THIS candidate the async
# screening link — no booked time, no human interviewer, no meeting URL.
# ============================================================================

cr_router = APIRouter(prefix="/screening", tags=["v2/screening"])


@cr_router.post("/candidate-rounds/{candidate_round_id}/invite")
async def invite_candidate_round(
    candidate_round_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    """Send (or re-send) the screening link to an existing candidate_round.

    ORG-SCOPED: candidate_round → candidate → requisition → org; 404 on any
    mismatch. Verifies the round is OpenRecruiting-hosted (round_screening_configs.enabled
    = true); 409 otherwise. Resolves the candidate's email + the round's
    validity_days, mints a fresh invite (superseding any prior active one), emails
    it, and returns {token, expires_at, verify_url} so the recruiter can copy the
    link even if email isn't configured locally.
    """
    cr_result = await (
        supabase.table("candidate_rounds")
        .select(
            "id, round_id, candidates(id, email, name, requisition_id, deleted_at, "
            "requisitions(id, organization_id, deleted_at, role_title))"
        )
        .eq("id", str(candidate_round_id))
        .single()
        .execute_async()
    )
    cr = cr_result.data
    if not cr:
        raise NotFoundError("Interview round not found")
    candidate = cr.get("candidates") or {}
    if candidate.get("deleted_at") is not None:
        raise NotFoundError("Interview round not found")
    req = candidate.get("requisitions") or {}
    if req.get("organization_id") != current.organization_id_str or req.get("deleted_at") is not None:
        raise NotFoundError("Interview round not found")

    round_id = cr.get("round_id")
    config = await ScreeningConfigService(supabase).get(str(round_id))
    if not config or not config.get("enabled"):
        raise ConflictError(
            "NOT_PLATFORM_HOSTED",
            "This round is not hosted by OpenRecruiting — schedule it with a human interviewer instead",
        )

    email = (candidate.get("email") or "").strip().lower()
    if not email:
        raise ValidationError("This candidate has no email on file to send the screening link to")

    validity_days = int(config.get("validity_days") or 7)
    result = await get_screening_invite_service().invite_existing_candidate_round(
        candidate_round_id=str(candidate_round_id),
        email=email,
        validity_days=validity_days,
        role_title=req.get("role_title"),
        candidate_name=candidate.get("name"),
    )

    logger.info(
        "screening.candidate_round_invited",
        extra={
            "candidate_round_id": str(candidate_round_id),
            "round_id": str(round_id),
            "validity_days": validity_days,
        },
    )
    return {**result, "validity_days": validity_days}
