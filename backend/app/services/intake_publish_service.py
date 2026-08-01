"""IntakePublishService — write the (possibly edited) interview_plan to canonical
tables (rounds + feedback_questions) and advance both requisition and session status.
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog

from app.services._supabase_rows import first_row, now_iso
from app.services.ats_sync.interview_actions import act_on_promoted_interviews
from app.services.intake._session_ops import load_owned_session

logger = structlog.get_logger(__name__)


class IntakePublishError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _validate_plan(plan: dict[str, Any]) -> None:
    if not isinstance(plan, dict):
        raise IntakePublishError("interview_plan must be a JSON object")
    rounds = plan.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        raise IntakePublishError("interview_plan.rounds must be a non-empty list")
    for i, r in enumerate(rounds):
        if not isinstance(r, dict):
            raise IntakePublishError(f"interview_plan.rounds[{i}] must be an object")
        if not r.get("name"):
            raise IntakePublishError(f"interview_plan.rounds[{i}] missing 'name'")
        if not r.get("category"):
            raise IntakePublishError(f"interview_plan.rounds[{i}] missing 'category'")
        fqs = r.get("feedback_questions")
        if not isinstance(fqs, list) or not fqs:
            raise IntakePublishError(f"interview_plan.rounds[{i}] missing feedback_questions")
        # Validate each question carries a 'heading' BEFORE publish() deletes the
        # existing rounds — otherwise a missing heading raises KeyError mid-insert,
        # after the delete, leaving the requisition with a partial round set.
        for j, q in enumerate(fqs):
            if not isinstance(q, dict) or not q.get("heading"):
                raise IntakePublishError(
                    f"interview_plan.rounds[{i}].feedback_questions[{j}] missing 'heading'"
                )
        # Pre-publish screening config is OPTIONAL on a round. Tolerate it (don't
        # require it, don't reject it) but reject a malformed shape BEFORE the
        # delete-then-insert so we never strand a partial round set.
        _validate_screening(r.get("screening"), f"interview_plan.rounds[{i}]")


def _validate_screening(screening: Any, where: str) -> None:
    """Tolerant validation of the optional per-round `screening` artifact object.

    OPTIONAL — absence is fine. When present it must be an object; its
    `questions` (if any) must be a list. We do NOT require enabled/questions — a
    disabled or empty screening config is a valid pre-publish state."""
    if screening is None:
        return
    if not isinstance(screening, dict):
        raise IntakePublishError(f"{where}.screening must be an object")
    questions = screening.get("questions")
    if questions is not None and not isinstance(questions, list):
        raise IntakePublishError(f"{where}.screening.questions must be a list")


class IntakePublishService:
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    async def publish(
        self,
        session_id: UUID,
        user_id: UUID,
        organization_id: UUID,
        edited_plan: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        # 1) Load session — scoped to caller's user + org
        row = await load_owned_session(
            self.supabase,
            session_id=session_id,
            user_id=user_id,
            organization_id=organization_id,
            columns="id,status,requisition_id,interview_plan",
        )
        if not row:
            raise IntakePublishError(f"Session {session_id} not found", status_code=404)
        # Allow publishing a freshly-submitted plan AND re-publishing an already
        # published one (the Hub's "Edit existing" flow reopens the plan editor on a
        # published session, edits, then publishes again). Rounds are deleted-then-
        # inserted below, so re-publish is idempotent.
        if row.get("status") not in ("submitted", "published"):
            raise IntakePublishError(
                f"Session is not ready to publish (status={row.get('status')})",
                status_code=409,
            )
        plan = edited_plan if edited_plan is not None else row.get("interview_plan")
        if not plan:
            raise IntakePublishError("No interview_plan to publish")
        _validate_plan(plan)

        requisition_id = row["requisition_id"]

        # 2) Replace existing rounds for this requisition (idempotent re-publish)
        await self.supabase.table("rounds").delete().eq("requisition_id", requisition_id).execute_async()

        # 3) Insert rounds + feedback_questions from the (possibly edited) plan.
        # Collect (new_round_id, screening) so screening is materialized AFTER all
        # rounds + questions are committed (see step 6).
        screening_to_materialize: list[tuple[str, dict]] = []
        for round_number, r in enumerate(plan["rounds"], start=1):
            round_insert = await self.supabase.table("rounds").insert({
                "requisition_id": requisition_id,
                "name": r["name"],
                "category": r.get("category"),
                "description": r.get("description"),
                "duration_minutes": r.get("duration_minutes", 45),
                "skills": r.get("skills", []),
                "round_number": round_number,
                "guidelines": r.get("guidelines", []),
                "ai_screenable": bool(r.get("ai_screenable", False)),
                "ai_screenable_reason": r.get("ai_screenable_reason"),
            }).execute_async()
            round_record = first_row(round_insert)
            if not round_record:
                raise IntakePublishError(f"Failed to insert round {r['name']}", status_code=500)
            new_round_id = round_record["id"]
            for question_number, q in enumerate(r["feedback_questions"], start=1):
                await self.supabase.table("feedback_questions").insert({
                    "round_id": new_round_id,
                    "heading": q["heading"],
                    "description": q.get("description") or "",
                    "question_number": question_number,
                }).execute_async()
            screening = r.get("screening")
            if isinstance(screening, dict) and screening.get("enabled"):
                screening_to_materialize.append((new_round_id, screening))

            # ATS plan-seeding (spec §8): persist the stage->round map for any
            # round the context-builder tagged with an Ashby stage id. Best-effort
            # per round — a map failure must not strand the published plan.
            ats_stage_id = r.get("ats_stage_id")
            if ats_stage_id:
                try:
                    from app.api.v2.core.rpc import call_rpc
                    await call_rpc(
                        self.supabase,
                        "ats_upsert_stage_round_map",
                        {
                            "p_org_id": str(organization_id),
                            "p_requisition_id": str(requisition_id),
                            "p_round_id": str(new_round_id),
                            "p_ats_stage_id": str(ats_stage_id),
                            "p_ats_stage_name": r.get("ats_stage_name"),
                        },
                    )
                except Exception as exc:  # noqa: BLE001 — never lose the published plan
                    logger.error(
                        "intake_v2_ats_stage_map_failed",
                        requisition_id=str(requisition_id),
                        round_id=str(new_round_id),
                        ats_stage_id=str(ats_stage_id),
                        error=str(exc),
                    )

        # 4) Flip requisition to 'planned' — scoped to org, idempotent via status guard
        await self.supabase.table("requisitions").update({
            "status": "planned",
        }).eq("id", requisition_id).eq("organization_id", str(organization_id)).in_("status", ["draft", "intake_pending"]).execute_async()

        # 5) Flip session to 'published' — also scoped to prevent mutating another org's row
        await self.supabase.table("intake_sessions").update({
            "status": "published",
            "published_at": now_iso(),
            "interview_plan": plan,
        }).eq("id", str(session_id)).eq("user_id", str(user_id)).eq("organization_id", str(organization_id)).execute_async()

        # 6) Materialize pre-publish screening config (carried in the plan artifact)
        # into the DB now that every round + its questions are committed. RESILIENT
        # by design: the rounds are already published, so a screening-materialization
        # failure is logged + skipped per round (the round still exists; screening
        # can be re-added on the dashboard) rather than failing the whole publish.
        # The screening_save_config RPC is idempotent on round_id (ON CONFLICT), so
        # re-publish re-applies the same config without duplication.
        for new_round_id, screening in screening_to_materialize:
            try:
                await self._materialize_screening(
                    round_id=new_round_id,
                    requisition_id=requisition_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    screening=screening,
                )
            except Exception as exc:  # noqa: BLE001 — never lose the published plan
                logger.error(
                    "intake_v2_screening_materialize_failed",
                    session_id=str(session_id),
                    round_id=str(new_round_id),
                    error=str(exc),
                )

        # ATS promotion (spec §9): stamp staged ats_interviews onto candidate_rounds
        # now that rounds + the stage map are written. Best-effort — the RPC no-ops
        # for non-ATS reqs (no ats_entity_links / no stage map), and any failure must
        # not break a successful publish. Phase C consumes the returned list
        # (Recall / transcript).
        try:
            from app.api.v2.core.rpc import call_rpc
            promoted = await call_rpc(
                self.supabase,
                "ats_promote_interviews",
                {"p_requisition_id": str(requisition_id), "p_org": str(organization_id)},
            )
            if promoted:
                logger.info(
                    "intake_v2_ats_promoted",
                    requisition_id=str(requisition_id),
                    promoted_count=len(promoted),
                )
            # Phase C: act on the promoted interviews (Recall auto-join for
            # future+URL, notetaker transcript pull, deferred feedback). No-op
            # for non-ATS reqs (promoted is empty). Best-effort — bundled in
            # this same guard so it can never break a successful publish.
            await act_on_promoted_interviews(self.supabase, promoted or [])
        except Exception as exc:  # noqa: BLE001 — never break a successful publish
            logger.error(
                "intake_v2_ats_promote_failed",
                requisition_id=str(requisition_id),
                error=str(exc),
            )

        logger.info("intake_v2_published", session_id=str(session_id), requisition_id=str(requisition_id))
        return {
            "session_id": str(session_id),
            "requisition_id": str(requisition_id),
            "redirect_url": f"/view/roles/{requisition_id}",
        }

    async def _materialize_screening(
        self,
        *,
        round_id: str,
        requisition_id: str,
        organization_id: UUID,
        user_id: UUID,
        screening: dict[str, Any],
    ) -> None:
        """Persist one round's pre-publish screening artifact into the DB.

        Reuses the same seams as the post-publish screening routes:
          - ScreeningConfigService.upsert → the atomic screening_save_config RPC
            (config + questions in one transaction, idempotent on round_id);
          - PersonaReduceService.persist_persona + ScreeningConfigService.set_persona
            to persist + attach the persona snapshot the FE captured during intake.

        Imported lazily to keep the publish service's import graph free of the
        api/v2 service layer (and to let tests seam-mock at the publish boundary)."""
        from app.api.v2.schemas.screening import ScreeningConfig, ScreeningQuestion
        from app.api.v2.services.persona_reduce_service import PersonaReduceService
        from app.api.v2.services.screening_config_service import ScreeningConfigService

        config = ScreeningConfig(
            round_id=round_id,
            enabled=bool(screening.get("enabled")),
            voice=screening.get("voice") or "aura-luna-en",
            follow_up_style=screening.get("follow_up_style") or "adaptive_probes",
            est_duration_minutes=screening.get("est_duration_minutes"),
            validity_days=int(screening.get("validity_days") or 7),
            deploy_scope=screening.get("deploy_scope") or "manual",
            questions=[
                ScreeningQuestion(
                    order_index=q.get("order_index", idx),
                    title=q.get("title") or "",
                    prompt=q.get("prompt") or "",
                    probe=q.get("probe"),
                    signal=q.get("signal"),
                    dimension=q.get("dimension"),
                    duration_minutes=q.get("duration_minutes") or 5,
                )
                for idx, q in enumerate(screening.get("questions") or [])
                if isinstance(q, dict)
            ],
        )
        config_service = ScreeningConfigService(self.supabase)
        await config_service.upsert(
            config,
            requisition_id=str(requisition_id),
            created_by=str(user_id),
        )

        snapshot = screening.get("persona_snapshot")
        if isinstance(snapshot, dict) and snapshot.get("dimensions"):
            persona_id = await PersonaReduceService(self.supabase).persist_persona(
                requisition_id=str(requisition_id),
                org_id=str(organization_id),
                role_title=screening.get("role_title") or "",
                created_by=str(user_id),
                dimensions=snapshot.get("dimensions") or [],
                composed_text=snapshot.get("text") or "",
            )
            await config_service.set_persona(round_id, persona_id, snapshot)
