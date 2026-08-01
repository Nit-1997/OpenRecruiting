"""Recruiter-facing saved persona library (org-scoped CRUD).

  GET    /personas           → list the org's personas (optional ?templates=true)
  POST   /personas           → create a persona (composed_text rendered server-side)
  PUT    /personas/{id}      → update (recompose composed_text when dimensions change)
  DELETE /personas/{id}      → hard delete (the table has no deleted_at)

Every route is gated by `get_current_user_with_org` and scoped to
`current.organization_id` — a caller can never read or mutate another org's
personas. composed_text is always rendered by intake-core's `compose_persona`
(via the service) so library personas stay anchored to the same wording the
runtime voice agent uses. This is the "lever" toward reusable personas: save one
as a template (is_template=true) and pick it for any round via the screening
`persona/select` route.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.v2.core.dependencies import (
    CurrentUserWithOrg,
    get_current_user_with_org,
    get_supabase,
)
from app.api.v2.schemas.screening import (
    CreatePersonaRequest,
    PersonaLibraryItem,
    UpdatePersonaRequest,
)
from app.api.v2.services.persona_library_service import (
    PersonaLibraryService,
    compose_dimensions,
)


router = APIRouter(prefix="/personas", tags=["v2/personas"])


@router.get("", response_model=list[PersonaLibraryItem])
async def list_personas(
    templates: bool = Query(
        False, description="When true, only return reusable templates."
    ),
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> list[dict]:
    return await PersonaLibraryService(supabase).list(
        org_id=current.organization_id_str, templates_only=templates
    )


@router.post("", response_model=PersonaLibraryItem, status_code=201)
async def create_persona(
    body: CreatePersonaRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    composed_text = compose_dimensions(body.dimensions)
    return await PersonaLibraryService(supabase).create(
        org_id=current.organization_id_str,
        name=body.name,
        dimensions=body.dimensions,
        composed_text=composed_text,
        is_template=body.is_template,
        created_by=str(current.user.id),
    )


@router.put("/{persona_id}", response_model=PersonaLibraryItem)
async def update_persona(
    persona_id: UUID,
    body: UpdatePersonaRequest,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> dict:
    # Recompose only when the dimensions actually change (compose_persona always
    # re-appends the guardrails).
    composed_text = compose_dimensions(body.dimensions) if body.dimensions is not None else None
    return await PersonaLibraryService(supabase).update(
        str(persona_id),
        org_id=current.organization_id_str,
        name=body.name,
        dimensions=body.dimensions,
        composed_text=composed_text,
        is_template=body.is_template,
    )


@router.delete("/{persona_id}", status_code=204)
async def delete_persona(
    persona_id: UUID,
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    supabase=Depends(get_supabase),
) -> Response:
    await PersonaLibraryService(supabase).delete(
        str(persona_id), org_id=current.organization_id_str
    )
    return Response(status_code=204)
