"""Org-scoped CRUD for the saved persona library.

A persona row (table `personas`, migration 116 + 118) can be:
  - round-bound (requisition_id set) — the derive/edit path on a single round, OR
  - a reusable org template (is_template=true, requisition_id NULL) the recruiter
    can pick for any round.

This service owns the library list/create/update/delete + a scoped `get` used by
the round `persona/select` route. Every method scopes to `org_id` so a caller can
never read or mutate another org's personas. `composed_text` is always rendered
by intake-core's `compose_persona` (never re-stated here) so the library persona
and the runtime voice agent stay anchored to the same wording — mirroring
PersonaReduceService.persist_persona.
"""

from __future__ import annotations

from datetime import datetime, timezone

from intake_core.screening.persona import (
    PersonaDimension,
    compose_persona,
)

from app.api.v2.core.exceptions import NotFoundError

# Columns returned to the API (kept lean — no created_by / timestamps churn).
_SELECT = (
    "id, organization_id, requisition_id, name, dimensions, composed_text, "
    "is_template, derived_at"
)


def _dimensions_payload(dimensions) -> list[dict]:
    """Render the API dimension models into the DB snapshot dimension shape."""
    dims = [
        PersonaDimension(
            key=d.key,
            value=d.value,
            confidence=d.confidence,
            source=d.source,
        )
        for d in dimensions
    ]
    return [
        {
            "key": d.key,
            "value": d.value,
            "confidence": d.confidence,
            "source": d.source,
        }
        for d in dims
    ]


def compose_dimensions(dimensions) -> str:
    """Render API dimension models into composed_text (always appends guardrails)."""
    dims = [
        PersonaDimension(
            key=d.key,
            value=d.value,
            confidence=d.confidence,
            source=d.source,
        )
        for d in dimensions
    ]
    return compose_persona(dims)


class PersonaLibraryService:
    def __init__(self, supabase):
        self.supabase = supabase

    async def list(self, *, org_id: str, templates_only: bool = False) -> list[dict]:
        query = (
            self.supabase.table("personas")
            .select(_SELECT)
            .eq("organization_id", org_id)
        )
        if templates_only:
            query = query.eq("is_template", "true")
        result = await query.order("derived_at", desc=True).execute_async()
        return result.data or []

    async def get(self, persona_id: str, *, org_id: str) -> dict:
        """Load one persona, scoped to org. 404 if missing or cross-org."""
        result = await (
            self.supabase.table("personas")
            .select(_SELECT)
            .eq("id", persona_id)
            .eq("organization_id", org_id)
            .single()
            .execute_async()
        )
        if not result.data:
            raise NotFoundError("Persona not found")
        return result.data

    async def create(
        self,
        *,
        org_id: str,
        name: str | None,
        dimensions,
        composed_text: str,
        is_template: bool,
        created_by: str | None,
    ) -> dict:
        payload = {
            "organization_id": org_id,
            # Templates are org-level (not bound to a requisition).
            "requisition_id": None,
            "name": name,
            "dimensions": _dimensions_payload(dimensions),
            "composed_text": composed_text,
            "is_template": is_template,
        }
        if created_by:
            payload["created_by"] = created_by
        result = await (
            self.supabase.table("personas").insert(payload).execute_async()
        )
        row = result.data or {}
        return row if isinstance(row, dict) else {}

    async def update(
        self,
        persona_id: str,
        *,
        org_id: str,
        name: str | None,
        dimensions,
        composed_text: str | None,
        is_template: bool | None,
    ) -> dict:
        """Partial update, org-scoped. 404 if the persona is missing or in another
        org. Caller pre-checks existence via `get` so the 404 is deterministic."""
        await self.get(persona_id, org_id=org_id)

        patch: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if name is not None:
            patch["name"] = name
        if dimensions is not None:
            patch["dimensions"] = _dimensions_payload(dimensions)
            patch["composed_text"] = composed_text
        if is_template is not None:
            patch["is_template"] = is_template

        await (
            self.supabase.table("personas")
            .update(patch)
            .eq("id", persona_id)
            .eq("organization_id", org_id)
            .execute_async()
        )
        return await self.get(persona_id, org_id=org_id)

    async def delete(self, persona_id: str, *, org_id: str) -> None:
        """Hard delete (the table has no deleted_at), org-scoped. 404 if missing
        or cross-org."""
        await self.get(persona_id, org_id=org_id)
        await (
            self.supabase.table("personas")
            .delete()
            .eq("id", persona_id)
            .eq("organization_id", org_id)
            .execute_async()
        )

    @staticmethod
    def snapshot_from_row(row: dict) -> dict:
        """Build a persona_snapshot {dimensions, text} from a stored row so it can
        be attached to a round via ScreeningConfigService.set_persona."""
        return {
            "dimensions": row.get("dimensions") or [],
            "text": row.get("composed_text") or "",
        }
