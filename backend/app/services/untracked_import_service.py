from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx

from app.logging_config import get_logger
from app.services._supabase_rows import is_unique_violation
from app.services.candidate_service import get_candidate_service
from app.services.feedback_job_service import get_feedback_job_service
from app.services.untracked_capture_service import GENERIC_TEMPLATE_CONFIG

logger = get_logger(__name__)


class UntrackedImportError(Exception):
    def __init__(self, status_code: int, detail: str | dict[str, Any]):
        self.status_code = status_code
        self.detail = detail
        if isinstance(detail, dict):
            message = str(detail.get("message") or "Untracked import error")
        else:
            message = detail
        super().__init__(message)


def _first_row(data):
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data
    return None


def _is_unique_violation(exc: Exception) -> bool:
    # Delegate to the shared helper so SQLSTATE 23505 (which the message-only
    # check missed) is recognised as well as the legacy message substrings.
    return is_unique_violation(exc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_synthetic_email(email: str) -> bool:
    return email.lower().endswith("@untracked.local")


EXISTING_ROUND_CONFLICT_CODE = "existing_round_conflict"


class UntrackedImportService:
    def __init__(self, supabase):
        self.supabase = supabase

    async def list_target_rounds(self, req_id: str, org_id: str) -> list[dict]:
        req = await self._get_target_requisition(req_id, org_id)
        if req.get("is_system_template"):
            raise UntrackedImportError(400, "Cannot import into system requisition")

        rounds = await self.supabase.table("rounds") \
            .select("id, name, round_number") \
            .eq("requisition_id", req_id) \
            .is_("deleted_at", "null") \
            .order("round_number") \
            .execute_async()

        return rounds.data or []

    async def list_untracked_interviews(
        self,
        req_id: str,
        org_id: str,
        page: int = 1,
        page_size: int = 25,
        import_view: str = "available",
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> dict:
        req = await self._get_target_requisition(req_id, org_id)
        if req.get("is_system_template"):
            raise UntrackedImportError(400, "Cannot import into system requisition")

        records = await self._list_generic_capture_rows(
            org_id=org_id,
            date_from=date_from,
            date_to=date_to,
        )
        if not records:
            return self._empty_page(page, page_size)

        source_round_ids = [str(r.get("source_candidate_round_id") or "") for r in records]
        source_round_ids = [sid for sid in source_round_ids if sid]
        detection_ids = list({
            str(r.get("source_detection_id") or "")
            for r in records
            if str(r.get("source_detection_id") or "")
        })

        imports_data: list[dict] = []
        if source_round_ids:
            imports_by_source = await self.supabase.table("untracked_interview_imports") \
                .select("id, source_generic_candidate_round_id, source_detection_id, target_requisition_id, import_status, created_at") \
                .in_("source_generic_candidate_round_id", source_round_ids) \
                .execute_async()
            imports_data.extend(imports_by_source.data or [])
        if detection_ids:
            imports_by_detection = await self.supabase.table("untracked_interview_imports") \
                .select("id, source_generic_candidate_round_id, source_detection_id, target_requisition_id, import_status, created_at") \
                .in_("source_detection_id", detection_ids) \
                .execute_async()
            imports_data.extend(imports_by_detection.data or [])

        latest_import_any_by_source: dict[str, dict] = {}
        latest_import_any_by_detection: dict[str, dict] = {}
        for row in imports_data:
            source_id = str(row.get("source_generic_candidate_round_id") or "")
            if not source_id:
                source_id = ""
            source_detection_id = str(row.get("source_detection_id") or "")
            created_at = str(row.get("created_at") or "")
            if source_id:
                existing = latest_import_any_by_source.get(source_id)
                if not existing or created_at > str(existing.get("created_at") or ""):
                    latest_import_any_by_source[source_id] = row
            if source_detection_id:
                existing_detection = latest_import_any_by_detection.get(source_detection_id)
                if not existing_detection or created_at > str(existing_detection.get("created_at") or ""):
                    latest_import_any_by_detection[source_detection_id] = row

        enriched_records: list[dict] = []
        for row in records:
            source_round_id = str(row.get("source_candidate_round_id") or "")
            if not source_round_id:
                continue
            source_detection_id = str(row.get("source_detection_id") or "")
            import_row_any = latest_import_any_by_source.get(source_round_id)
            if not import_row_any and source_detection_id:
                import_row_any = latest_import_any_by_detection.get(source_detection_id)
            import_row = import_row_any
            status_value = import_row.get("import_status") if import_row else "available"
            row["status"] = status_value
            if import_row:
                row["imported_requisition_id"] = str(import_row.get("target_requisition_id") or "") or None
                row["imported_at"] = import_row.get("created_at")
            enriched_records.append(row)

        imported_req_ids = list({
            str(row.get("imported_requisition_id"))
            for row in enriched_records
            if row.get("imported_requisition_id")
        })
        imported_req_titles: dict[str, str] = {}
        if imported_req_ids:
            reqs_result = await self.supabase.table("requisitions") \
                .select("id, role_title") \
                .in_("id", imported_req_ids) \
                .is_("deleted_at", "null") \
                .execute_async()
            imported_req_titles = {
                str(row.get("id")): str(row.get("role_title") or "")
                for row in (reqs_result.data or [])
            }
            for row in enriched_records:
                imported_req_id = str(row.get("imported_requisition_id") or "")
                row["imported_requisition_title"] = imported_req_titles.get(imported_req_id) or None

        filtered_records = self._filter_rows_by_import_view(enriched_records, import_view)

        total = len(filtered_records)
        logger.info(
            "untracked_import.list_requisition req_id=%s view=%s records_total=%s records_filtered=%s imports_seen=%s",
            req_id,
            import_view,
            len(records),
            total,
            len(imports_data),
        )

        offset = (page - 1) * page_size
        paged = filtered_records[offset: offset + page_size]

        return {
            "items": paged,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def list_org_untracked_interviews(
        self,
        org_id: str,
        page: int = 1,
        page_size: int = 25,
        import_view: str = "available",
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> dict:
        records = await self._list_generic_capture_rows(
            org_id=org_id,
            date_from=date_from,
            date_to=date_to,
        )
        if not records:
            return self._empty_page(page, page_size)

        source_round_ids = [str(r.get("source_candidate_round_id") or "") for r in records]
        source_round_ids = [sid for sid in source_round_ids if sid]

        latest_import_by_source: dict[str, dict] = {}
        latest_import_by_detection: dict[str, dict] = {}
        if source_round_ids:
            imports_result = await self.supabase.table("untracked_interview_imports") \
                .select("source_generic_candidate_round_id, source_detection_id, import_status, target_requisition_id, created_at") \
                .in_("source_generic_candidate_round_id", source_round_ids) \
                .execute_async()

            for row in (imports_result.data or []):
                source_id = str(row.get("source_generic_candidate_round_id") or "")
                if not source_id:
                    source_id = ""
                source_detection_id = str(row.get("source_detection_id") or "")
                created_at = str(row.get("created_at") or "")
                if source_id:
                    existing = latest_import_by_source.get(source_id)
                    if not existing or created_at > str(existing.get("created_at") or ""):
                        latest_import_by_source[source_id] = row
                if source_detection_id:
                    existing_detection = latest_import_by_detection.get(source_detection_id)
                    if not existing_detection or created_at > str(existing_detection.get("created_at") or ""):
                        latest_import_by_detection[source_detection_id] = row

        detection_ids = list({
            str(r.get("source_detection_id") or "")
            for r in records
            if str(r.get("source_detection_id") or "")
        })
        if detection_ids:
            detection_imports = await self.supabase.table("untracked_interview_imports") \
                .select("source_generic_candidate_round_id, source_detection_id, import_status, target_requisition_id, created_at") \
                .in_("source_detection_id", detection_ids) \
                .execute_async()
            for row in (detection_imports.data or []):
                source_detection_id = str(row.get("source_detection_id") or "")
                if not source_detection_id:
                    continue
                created_at = str(row.get("created_at") or "")
                existing_detection = latest_import_by_detection.get(source_detection_id)
                if not existing_detection or created_at > str(existing_detection.get("created_at") or ""):
                    latest_import_by_detection[source_detection_id] = row

        imported_req_ids = list({
            str(row.get("target_requisition_id"))
            for row in [*latest_import_by_source.values(), *latest_import_by_detection.values()]
            if row.get("target_requisition_id")
        })
        imported_req_titles: dict[str, str] = {}
        if imported_req_ids:
            reqs_result = await self.supabase.table("requisitions") \
                .select("id, role_title") \
                .in_("id", imported_req_ids) \
                .is_("deleted_at", "null") \
                .execute_async()
            imported_req_titles = {
                str(row.get("id")): str(row.get("role_title") or "")
                for row in (reqs_result.data or [])
            }

        for row in records:
            source_round_id = str(row.get("source_candidate_round_id") or "")
            source_detection_id = str(row.get("source_detection_id") or "")
            import_row = latest_import_by_source.get(source_round_id)
            if not import_row and source_detection_id:
                import_row = latest_import_by_detection.get(source_detection_id)
            if not import_row:
                row["status"] = "available"
                continue

            target_req_id = str(import_row.get("target_requisition_id") or "")
            row["status"] = str(import_row.get("import_status") or "available")
            row["imported_requisition_id"] = target_req_id or None
            row["imported_requisition_title"] = imported_req_titles.get(target_req_id) or None
            row["imported_at"] = import_row.get("created_at")

        filtered_records = self._filter_rows_by_import_view(records, import_view)

        total = len(filtered_records)
        logger.info(
            "untracked_import.list_org org_id=%s view=%s records_total=%s records_filtered=%s",
            org_id,
            import_view,
            len(records),
            total,
        )
        offset = (page - 1) * page_size
        paged = filtered_records[offset: offset + page_size]
        return {
            "items": paged,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def _filter_rows_by_import_view(
        self,
        rows: list[dict],
        import_view: str,
    ) -> list[dict]:
        if import_view == "all":
            return rows
        if import_view == "imported":
            return [row for row in rows if str(row.get("status") or "available") != "available"]
        return [row for row in rows if str(row.get("status") or "available") == "available"]

    async def get_untracked_interview_packet(
        self,
        source_candidate_round_id: str,
        org_id: str,
    ) -> dict:
        source_round_result = await self.supabase.table("candidate_rounds") \
            .select(
                "id, candidate_id, round_id, source_type, origin_detection_id, status, "
                "scheduled_at, completed_at, interviewer_email, meeting_url, transcript_url, "
                "recording_url, scorecard_transcript, summary, rating, question_summaries, processing_status"
            ) \
            .eq("id", source_candidate_round_id) \
            .limit(1) \
            .execute_async()
        source_round = _first_row(source_round_result.data)
        if not source_round:
            raise UntrackedImportError(404, "Source interview not found")
        if source_round.get("source_type") != "untracked_generic":
            raise UntrackedImportError(400, "Invalid source interview")

        source_candidate = await self._get_candidate(str(source_round["candidate_id"]))
        source_requisition = await self._get_requisition(str(source_candidate["requisition_id"]))
        if str(source_requisition.get("organization_id")) != str(org_id):
            raise UntrackedImportError(403, "Forbidden")
        if not bool(source_requisition.get("is_system_template")):
            raise UntrackedImportError(400, "Invalid source interview")

        source_media = await self._resolve_source_round_media(
            source_candidate_round_id=source_candidate_round_id,
            source_detection_id=str(source_round.get("origin_detection_id") or ""),
            source_round=source_round,
        )

        source_round_def_result = await self.supabase.table("rounds") \
            .select("id, name, round_number") \
            .eq("id", str(source_round.get("round_id"))) \
            .is_("deleted_at", "null") \
            .limit(1) \
            .execute_async()
        source_round_def = _first_row(source_round_def_result.data)
        if not source_round_def:
            raise UntrackedImportError(404, "Round not found")

        questions_result = await self.supabase.table("feedback_questions") \
            .select("id, question_number, heading, description") \
            .eq("round_id", str(source_round.get("round_id"))) \
            .is_("deleted_at", "null") \
            .order("question_number") \
            .execute_async()
        questions = questions_result.data or []

        feedback_result = await self.supabase.table("candidate_feedback") \
            .select("id, feedback_question_id, feedback_text, evidence, evidence_status, source, created_at, updated_at") \
            .eq("candidate_round_id", source_candidate_round_id) \
            .order("created_at") \
            .execute_async()
        feedback_rows = feedback_result.data or []

        feedback_by_question: dict[str, list[dict]] = {}
        for row in feedback_rows:
            qid = str(row.get("feedback_question_id") or "")
            if not qid:
                continue
            feedback_by_question.setdefault(qid, []).append(row)

        question_summaries = source_round.get("question_summaries") or {}
        feedback_questions: list[dict] = []
        for q in questions:
            q_id = str(q.get("id") or "")
            q_num = int(q.get("question_number") or 0)
            entries: list[dict] = []
            for fb in feedback_by_question.get(q_id, []):
                entries.append({
                    "id": fb.get("id"),
                    "feedback_data": fb.get("feedback_text"),
                    "evidence": fb.get("evidence") or [],
                    "evidence_status": fb.get("evidence_status"),
                    "source": fb.get("source"),
                    "created_at": fb.get("created_at"),
                    "updated_at": fb.get("updated_at"),
                })
            feedback_questions.append({
                "id": q.get("id"),
                "question_number": q_num,
                "heading": q.get("heading") or "",
                "description": q.get("description"),
                "summary": question_summaries.get(str(q_num)) if isinstance(question_summaries, dict) else None,
                "feedback": entries,
            })

        detection = {}
        detection_id = source_round.get("origin_detection_id")
        if detection_id:
            detection_result = await self.supabase.table("calendar_event_detections") \
                .select("event_title, event_start") \
                .eq("id", str(detection_id)) \
                .limit(1) \
                .execute_async()
            detection = _first_row(detection_result.data) or {}

        return {
            "source_candidate_round_id": source_round["id"],
            "source_candidate_id": source_candidate["id"],
            "source_requisition_id": source_requisition["id"],
            "candidate_name": source_candidate.get("name") or "Unknown Candidate",
            "candidate_email": source_candidate.get("email") or "",
            "requisition_title": source_requisition.get("role_title") or "Untracked Interviews",
            "round_id": source_round.get("round_id"),
            "round_name": source_round_def.get("name") or "Generic Interview",
            "round_number": source_round_def.get("round_number") or 1,
            "event_title": detection.get("event_title") or "Interview",
            "event_start": detection.get("event_start") or source_round.get("scheduled_at"),
            "status": source_round.get("status") or "scheduled",
            "processing_status": source_round.get("processing_status"),
            "summary": source_round.get("summary"),
            "rating": source_round.get("rating"),
            "interviewer_email": source_round.get("interviewer_email"),
            "meeting_url": source_round.get("meeting_url"),
            "transcript_url": source_media.get("transcript_url"),
            "recording_url": source_media.get("recording_url"),
            "scorecard_transcript": source_round.get("scorecard_transcript"),
            "feedback_questions": feedback_questions,
        }

    def _empty_page(self, page: int, page_size: int) -> dict:
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
        }

    async def _list_generic_capture_rows(
        self,
        org_id: str,
        *,
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> list[dict]:
        binding_result = await self.supabase.table("org_generic_template_bindings") \
            .select("materialized_requisition_id") \
            .eq("organization_id", org_id) \
            .eq("template_key", GENERIC_TEMPLATE_CONFIG["template_key"]) \
            .limit(1) \
            .execute_async()
        binding = _first_row(binding_result.data)
        if not binding:
            return []

        generic_requisition_id = str(binding["materialized_requisition_id"])

        candidates_result = await self.supabase.table("candidates") \
            .select("id, requisition_id, name, email") \
            .eq("requisition_id", generic_requisition_id) \
            .is_("deleted_at", "null") \
            .execute_async()
        candidates = candidates_result.data or []
        if not candidates:
            return []

        candidate_by_id = {str(c["id"]): c for c in candidates}
        candidate_ids = list(candidate_by_id.keys())
        if not candidate_ids:
            return []

        rounds_result = await self.supabase.table("candidate_rounds") \
            .select("id, candidate_id, origin_detection_id, interviewer_email, status, scheduled_at") \
            .in_("candidate_id", candidate_ids) \
            .eq("source_type", "untracked_generic") \
            .neq("status", "cancelled") \
            .execute_async()
        source_rounds = rounds_result.data or []
        if not source_rounds:
            return []

        detection_ids = [str(r.get("origin_detection_id")) for r in source_rounds if r.get("origin_detection_id")]
        detections_by_id = {}
        if detection_ids:
            detections_result = await self.supabase.table("calendar_event_detections") \
                .select("id, event_title, event_start") \
                .in_("id", detection_ids) \
                .execute_async()
            detections_by_id = {
                str(d["id"]): d
                for d in (detections_result.data or [])
            }

        records: list[dict] = []
        for source_round in source_rounds:
            source_round_id = str(source_round.get("id") or "")
            candidate = candidate_by_id.get(str(source_round.get("candidate_id") or ""))
            if not source_round_id or not candidate:
                continue

            detection = detections_by_id.get(str(source_round.get("origin_detection_id") or ""), {})
            event_start_raw = detection.get("event_start") or source_round.get("scheduled_at")
            event_start_dt = self._parse_event_start(event_start_raw)

            if date_from and event_start_dt and event_start_dt.date() < date_from:
                continue
            if date_to and event_start_dt and event_start_dt.date() > date_to:
                continue

            records.append({
                "source_candidate_round_id": source_round_id,
                "source_candidate_id": str(candidate.get("id") or ""),
                "source_requisition_id": str(candidate.get("requisition_id") or ""),
                "source_detection_id": str(source_round.get("origin_detection_id") or ""),
                "candidate_name": candidate.get("name") or "Unknown Candidate",
                "candidate_email": candidate.get("email") or "",
                "event_title": detection.get("event_title") or "Interview",
                "event_start": event_start_raw,
                "interviewer_email": source_round.get("interviewer_email"),
                "status": "available",
                "imported_requisition_id": None,
                "imported_requisition_title": None,
                "imported_at": None,
            })

        records.sort(key=lambda row: str(row.get("event_start") or ""), reverse=True)
        return records

    def _parse_event_start(self, value) -> Optional[datetime]:
        if not isinstance(value, str):
            return None
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    async def import_untracked_interview(
        self,
        req_id: str,
        source_candidate_round_id: str,
        target_round_id: str,
        org_id: str,
        imported_by_user_id: Optional[str],
        override_existing_round: bool = False,
    ) -> dict:
        source_round = await self._get_source_round(source_candidate_round_id)
        source_candidate = await self._get_candidate(str(source_round["candidate_id"]))
        source_requisition = await self._get_requisition(str(source_candidate["requisition_id"]))

        if str(source_requisition.get("organization_id")) != str(org_id):
            raise UntrackedImportError(403, "Forbidden")
        if not bool(source_requisition.get("is_system_template")):
            raise UntrackedImportError(400, "Invalid source interview")

        target_req = await self._get_target_requisition(req_id, org_id)
        if target_req.get("is_system_template"):
            raise UntrackedImportError(400, "Cannot import into system requisition")

        target_round = await self.supabase.table("rounds") \
            .select("id") \
            .eq("id", target_round_id) \
            .eq("requisition_id", req_id) \
            .is_("deleted_at", "null") \
            .limit(1) \
            .execute_async()
        if not target_round.data:
            raise UntrackedImportError(400, "Round not found in this requisition")

        logger.info(
            "untracked_import.started source_cr_id=%s source_candidate_id=%s source_detection_id=%s target_req_id=%s target_round_id=%s",
            source_candidate_round_id,
            str(source_candidate.get("id") or ""),
            str(source_round.get("origin_detection_id") or ""),
            req_id,
            target_round_id,
        )

        # UNTRACKED-MA: an untracked interview is flexibly re-associable. The
        # source-level hard-block that used to 409 a second import in another
        # requisition is now a SUPERSEDE of the source's current active attempt —
        # but it is DEFERRED to after the target-conflict checks below (see the
        # supersede call past the conflict block). Superseding here, before those
        # checks, meant an EXISTING_ROUND_CONFLICT 409 (or any later validation
        # failure) retired the prior attempt without creating a replacement,
        # leaving the source with zero active imports. The genuine same-target
        # dedup is still preserved by uq_import_source_target at the audit insert.
        source_detection_id = str(source_round.get("origin_detection_id") or "")

        source_media = await self._resolve_source_round_media(
            source_candidate_round_id=source_candidate_round_id,
            source_detection_id=source_detection_id,
            source_round=source_round,
        )

        target_candidate_id, candidate_created = await self._resolve_target_candidate(
            target_requisition_id=req_id,
            source_candidate=source_candidate,
            source_candidate_round_id=source_candidate_round_id,
            org_id=org_id,
        )

        conflict = await self.supabase.table("candidate_rounds") \
            .select("id, status, source_type, origin_candidate_round_id, recording_url, transcript_url, scorecard_transcript, completed_at") \
            .eq("candidate_id", target_candidate_id) \
            .eq("round_id", target_round_id) \
            .limit(1) \
            .execute_async()
        conflict_row = _first_row(conflict.data)
        reuse_existing_round = False
        if conflict_row and candidate_created:
            reuse_existing_round = True
        elif conflict_row and not override_existing_round:
            candidate_email = str(source_candidate.get("email") or "")
            if not candidate_email or _is_synthetic_email(candidate_email):
                target_candidate_result = await self.supabase.table("candidates") \
                    .select("email") \
                    .eq("id", target_candidate_id) \
                    .limit(1) \
                    .execute_async()
                target_candidate_row = _first_row(target_candidate_result.data)
                if target_candidate_row:
                    candidate_email = str(target_candidate_row.get("email") or "")
            raise UntrackedImportError(
                409,
                {
                    "code": EXISTING_ROUND_CONFLICT_CODE,
                    "message": "This candidate already has this round. Do you want to override it?",
                    "conflict": {
                        "candidate_id": target_candidate_id,
                        "candidate_email": candidate_email,
                        "target_round_id": target_round_id,
                        "target_candidate_round_id": str(conflict_row.get("id") or ""),
                        "existing_status": str(conflict_row.get("status") or ""),
                        "has_recording": bool(conflict_row.get("recording_url")),
                        "has_transcript": bool(
                            conflict_row.get("transcript_url")
                            or conflict_row.get("scorecard_transcript")
                        ),
                        "completed_at": conflict_row.get("completed_at"),
                    },
                },
            )
        elif conflict_row and override_existing_round:
            reuse_existing_round = True

        # Now committed to creating/reusing the target round (all conflict checks
        # above passed) — retire the source's prior active attempt: superseded_at
        # =now() + its candidate_round cancelled, feedback rows KEPT so the prior
        # attempt stays restorable. Deferred to here so an EXISTING_ROUND_CONFLICT
        # 409 above can't leave the source with no active import.
        await self._supersede_prior_active_import(
            source_candidate_round_id=source_candidate_round_id,
            source_detection_id=source_detection_id,
            req_id=req_id,
        )

        target_candidate_round_id: Optional[str] = None
        cleanup_needed = False

        try:
            insert_payload = {
                "candidate_id": target_candidate_id,
                "round_id": target_round_id,
                "status": "completed",
                "source_type": "untracked_copy",
                "origin_candidate_round_id": source_candidate_round_id,
                "origin_detection_id": source_round.get("origin_detection_id"),
                "scheduled_at": source_round.get("scheduled_at"),
                "completed_at": source_round.get("completed_at"),
                "interviewer_email": source_round.get("interviewer_email"),
                "meeting_url": source_round.get("meeting_url"),
                "scorecard_transcript": source_round.get("scorecard_transcript"),
                "transcript_url": source_media.get("transcript_url"),
                "recording_url": source_media.get("recording_url"),
                "processing_status": source_round.get("processing_status"),
                "scorecard_status": source_round.get("scorecard_status"),
                "summary": source_round.get("summary"),
                "rating": source_round.get("rating"),
                "question_summaries": source_round.get("question_summaries"),
                "outcome": source_round.get("outcome"),
                "outcome_notes": source_round.get("outcome_notes"),
            }
            if reuse_existing_round and conflict_row:
                target_candidate_round_id = str(conflict_row["id"])
                updated = await self.supabase.table("candidate_rounds") \
                    .update(insert_payload | {"updated_at": _now_iso()}) \
                    .eq("id", target_candidate_round_id) \
                    .execute_async()
                if not updated.data:
                    raise RuntimeError("Failed to update existing target candidate round")
            else:
                target_round_insert = await self.supabase.table("candidate_rounds") \
                    .insert(insert_payload) \
                    .execute_async()
                inserted = _first_row(target_round_insert.data)
                if not inserted:
                    raise RuntimeError("Failed to create target candidate round")
                target_candidate_round_id = str(inserted["id"])
                cleanup_needed = True

            await self._copy_transcript_record(
                source_candidate_round_id=source_candidate_round_id,
                target_candidate_round_id=target_candidate_round_id,
                fallback_transcript_url=source_media.get("transcript_url"),
                fallback_duration_seconds=source_media.get("recording_duration_seconds"),
                fallback_participants=source_media.get("participants"),
            )

            # CLAIM the import under uq_import_source_target BEFORE triggering
            # feedback. UNTRACKED-MA: a source may hold multiple attempts, so
            # there is no source-only unique index any more — the remaining DB
            # guard is uq_import_source_target (source, target_req, target_round),
            # which serializes an accidental concurrent same-target double-submit.
            # The supersede step earlier already retired the prior active attempt
            # (different target). Under a same-target double-submit both requests
            # pass the checks, so the loser's audit insert raises unique_violation
            # (23505). Inserting the audit row HERE (before the Lambda trigger)
            # guarantees a losing request never fires feedback; its orphan
            # candidate_round is cancelled by the except handler below.
            audit_payload = {
                "organization_id": org_id,
                "source_detection_id": source_round.get("origin_detection_id"),
                "source_generic_candidate_id": source_candidate.get("id"),
                "source_generic_candidate_round_id": source_candidate_round_id,
                "target_requisition_id": req_id,
                "target_round_id": target_round_id,
                "target_candidate_id": target_candidate_id,
                "target_candidate_round_id": target_candidate_round_id,
                "import_status": "copied",
                "error": None,
                "imported_by_user_id": imported_by_user_id,
            }

            try:
                import_result = await self.supabase.table("untracked_interview_imports") \
                    .insert(audit_payload) \
                    .execute_async()
            except Exception as audit_exc:
                if _is_unique_violation(audit_exc):
                    # Lost the race: another request already claimed this import.
                    # Roll back THIS request's orphan side effects (the round we
                    # just created and, if applicable, the candidate) so no
                    # duplicate active round survives, then surface 409. The
                    # 409 raise below skips the generic cleanup handler (it
                    # only fires for unexpected Exceptions), so we clean up
                    # explicitly here. Feedback was NOT triggered yet.
                    await self._cleanup_orphan_import(
                        target_candidate_round_id if cleanup_needed else None,
                        target_candidate_id if candidate_created else None,
                    )
                    raise UntrackedImportError(409, "Already imported to this round")
                raise

            import_row = _first_row(import_result.data)
            if not import_row:
                raise RuntimeError("Failed to persist import audit row")

            # We now own the import slot — safe to trigger feedback exactly once.
            question_count = await self.supabase.table("feedback_questions") \
                .select("id") \
                .eq("round_id", target_round_id) \
                .is_("deleted_at", "null") \
                .count_async()

            import_status = "copied"
            import_error: Optional[str] = None

            if question_count > 0:
                feedback_service = get_feedback_job_service()
                try:
                    trigger_result = await feedback_service.trigger_feedback_processing(target_candidate_round_id)
                    if str(trigger_result.get("status")) == "accepted":
                        import_status = "reprocessed"
                    else:
                        import_status = "reprocess_failed"
                        import_error = str(trigger_result.get("reason") or "Feedback processing was not accepted")
                except Exception as exc:
                    import_status = "reprocess_failed"
                    import_error = str(exc)[:500]
            else:
                import_status = "copied_pending_scorecard"

            # Stamp the final outcome onto the already-claimed audit row.
            if import_status != "copied":
                try:
                    await self.supabase.table("untracked_interview_imports") \
                        .update({
                            "import_status": import_status,
                            "error": import_error,
                            "updated_at": _now_iso(),
                        }) \
                        .eq("id", str(import_row.get("id"))) \
                        .execute_async()
                except Exception as status_exc:
                    logger.warning(
                        "untracked_import.audit_status_update_failed import_id=%s status=%s err=%s",
                        str(import_row.get("id") or ""),
                        import_status,
                        str(status_exc)[:200],
                    )

            cleanup_needed = False
            logger.info(
                "untracked_import.completed import_id=%s source_cr_id=%s target_cr_id=%s status=%s",
                str(import_row.get("id") or ""),
                source_candidate_round_id,
                str(target_candidate_round_id or ""),
                import_status,
            )

            return {
                "import_id": import_row["id"],
                "target_candidate_id": target_candidate_id,
                "target_candidate_round_id": target_candidate_round_id,
                "import_status": import_status,
                "candidate_created": candidate_created,
            }
        except UntrackedImportError:
            raise
        except Exception as exc:
            logger.error(
                "untracked_import.failed",
                extra={
                    "source_cr_id": source_candidate_round_id,
                    "target_req_id": req_id,
                    "target_round_id": target_round_id,
                    "error": str(exc)[:200],
                },
                exc_info=True,
            )

            await self._cleanup_orphan_import(
                target_candidate_round_id if cleanup_needed else None,
                target_candidate_id if candidate_created else None,
            )

            raise UntrackedImportError(500, "Import failed, please retry")

    async def _supersede_prior_active_import(
        self,
        *,
        source_candidate_round_id: str,
        source_detection_id: str,
        req_id: str,
    ) -> None:
        """UNTRACKED-MA forward reassign: retire the source's current active
        attempt before a new import claims the honored slot.

        Finds the newest non-dismissed import with superseded_at IS NULL for
        this untracked interview (by source round id, falling back to detection
        id), marks it superseded, and cancels its candidate_round — keeping its
        feedback rows so the prior attempt stays restorable. No-op when there is
        no active attempt. A failure to cancel the prior round is swallowed (the
        supersede stamp is the durable record); the new import still proceeds.
        """
        prior = await self._find_active_import(
            source_candidate_round_id=source_candidate_round_id,
            source_detection_id=source_detection_id,
        )
        if not prior:
            return

        logger.info(
            "untracked_import.supersede_prior source_cr_id=%s prior_import_id=%s "
            "prior_target_req_id=%s new_target_req_id=%s",
            source_candidate_round_id,
            str(prior.get("id") or ""),
            str(prior.get("target_requisition_id") or ""),
            req_id,
        )

        await self.supabase.table("untracked_interview_imports") \
            .update({"superseded_at": _now_iso(), "updated_at": _now_iso()}) \
            .eq("id", str(prior["id"])) \
            .execute_async()

        prior_round_id = prior.get("target_candidate_round_id")
        if prior_round_id:
            try:
                await self.supabase.table("candidate_rounds") \
                    .update({"status": "cancelled", "updated_at": _now_iso()}) \
                    .eq("id", str(prior_round_id)) \
                    .in_("status", ["pending", "scheduled", "completed"]) \
                    .execute_async()
            except Exception as exc:
                logger.warning(
                    "untracked_import.supersede_cancel_failed prior_round_id=%s err=%s",
                    str(prior_round_id),
                    str(exc)[:200],
                )

    async def _find_active_import(
        self,
        *,
        source_candidate_round_id: str,
        source_detection_id: str,
    ) -> Optional[dict]:
        """The honored attempt for an untracked interview: newest non-dismissed
        import with superseded_at IS NULL. Matched by source round id first,
        then detection id (both identify the same untracked interview)."""
        by_source = await self.supabase.table("untracked_interview_imports") \
            .select("id, target_requisition_id, target_round_id, target_candidate_round_id, import_status, superseded_at, created_at") \
            .eq("source_generic_candidate_round_id", source_candidate_round_id) \
            .order("created_at", desc=True) \
            .execute_async()
        active = self._first_active_row(by_source.data or [])
        if active:
            return active
        if source_detection_id:
            by_detection = await self.supabase.table("untracked_interview_imports") \
                .select("id, target_requisition_id, target_round_id, target_candidate_round_id, import_status, superseded_at, created_at") \
                .eq("source_detection_id", source_detection_id) \
                .order("created_at", desc=True) \
                .execute_async()
            return self._first_active_row(by_detection.data or [])
        return None

    @staticmethod
    def _first_active_row(rows: list[dict]) -> Optional[dict]:
        for row in rows:
            if str(row.get("import_status") or "") == "dismissed":
                continue
            if row.get("superseded_at") is None:
                return row
        return None

    async def _cleanup_orphan_import(
        self,
        candidate_round_id: Optional[str],
        candidate_id: Optional[str],
    ) -> None:
        """Best-effort rollback of a freshly-created round/candidate that did
        not complete (failure or lost import race). Cancels the round and
        soft-deletes a just-created candidate so no duplicate active row
        survives. Failures here are swallowed — the real outcome is the
        caller's raised error."""
        if candidate_round_id:
            try:
                await self.supabase.table("candidate_rounds") \
                    .update({"status": "cancelled", "updated_at": _now_iso()}) \
                    .eq("id", candidate_round_id) \
                    .in_("status", ["pending", "scheduled", "completed"]) \
                    .execute_async()
            except Exception:
                pass
        if candidate_id:
            try:
                await self.supabase.table("candidates") \
                    .update({"deleted_at": _now_iso(), "updated_at": _now_iso()}) \
                    .eq("id", candidate_id) \
                    .is_("deleted_at", "null") \
                    .execute_async()
            except Exception:
                pass

    async def _get_requisition(self, requisition_id: str) -> dict:
        req_result = await self.supabase.table("requisitions") \
            .select("id, organization_id, is_system_template, role_title") \
            .eq("id", requisition_id) \
            .is_("deleted_at", "null") \
            .limit(1) \
            .execute_async()
        req = _first_row(req_result.data)
        if not req:
            raise UntrackedImportError(404, "Requisition not found")
        return req

    async def _get_target_requisition(self, req_id: str, org_id: str) -> dict:
        req = await self._get_requisition(req_id)
        if str(req.get("organization_id")) != str(org_id):
            raise UntrackedImportError(403, "Forbidden")
        return req

    async def _get_source_round(self, source_candidate_round_id: str) -> dict:
        source_round_result = await self.supabase.table("candidate_rounds") \
            .select(
                "id, candidate_id, round_id, source_type, origin_detection_id, "
                "scheduled_at, completed_at, interviewer_email, meeting_url, scorecard_transcript, "
                "transcript_url, recording_url, processing_status, scorecard_status, "
                "summary, rating, question_summaries, outcome, outcome_notes"
            ) \
            .eq("id", source_candidate_round_id) \
            .limit(1) \
            .execute_async()
        source_round = _first_row(source_round_result.data)
        if not source_round:
            raise UntrackedImportError(404, "Source interview not found")
        if source_round.get("source_type") != "untracked_generic":
            raise UntrackedImportError(400, "Invalid source interview")
        return source_round

    async def _resolve_source_round_media(
        self,
        *,
        source_candidate_round_id: str,
        source_detection_id: str,
        source_round: dict,
    ) -> dict:
        resolved = {
            "recording_url": source_round.get("recording_url"),
            "transcript_url": source_round.get("transcript_url"),
            "recording_duration_seconds": None,
            "participants": None,
        }
        if resolved["recording_url"] and resolved["transcript_url"]:
            return resolved

        bot = await self._get_latest_source_recall_bot(
            source_candidate_round_id=source_candidate_round_id,
            source_detection_id=source_detection_id,
        )
        if not bot:
            return resolved

        if not resolved["recording_url"]:
            resolved["recording_url"] = bot.get("recording_url")
        if not resolved["transcript_url"]:
            resolved["transcript_url"] = bot.get("transcript_url")
        resolved["recording_duration_seconds"] = bot.get("recording_duration_seconds")
        resolved["participants"] = bot.get("participants")

        logger.info(
            "untracked_import.source_media_resolved source_cr_id=%s has_recording=%s has_transcript=%s source=recall_bots",
            source_candidate_round_id,
            bool(resolved.get("recording_url")),
            bool(resolved.get("transcript_url")),
        )
        return resolved

    async def _get_latest_source_recall_bot(
        self,
        *,
        source_candidate_round_id: str,
        source_detection_id: str,
    ) -> Optional[dict]:
        if source_candidate_round_id:
            by_round = await self.supabase.table("recall_bots") \
                .select("recording_url, transcript_url, recording_duration_seconds, participants, created_at") \
                .eq("candidate_round_id", source_candidate_round_id) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute_async()
            row = _first_row(by_round.data)
            if row:
                return row
        if source_detection_id:
            by_detection = await self.supabase.table("recall_bots") \
                .select("recording_url, transcript_url, recording_duration_seconds, participants, created_at") \
                .eq("detection_id", source_detection_id) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute_async()
            row = _first_row(by_detection.data)
            if row:
                return row
        return None

    async def _get_candidate(self, candidate_id: str) -> dict:
        result = await self.supabase.table("candidates") \
            .select("id, requisition_id, name, email") \
            .eq("id", candidate_id) \
            .is_("deleted_at", "null") \
            .limit(1) \
            .execute_async()
        row = _first_row(result.data)
        if not row:
            raise UntrackedImportError(404, "Source interview not found")
        return row

    async def _resolve_target_candidate(
        self,
        target_requisition_id: str,
        source_candidate: dict,
        source_candidate_round_id: str,
        org_id: str,
    ) -> tuple[str, bool]:
        source_email = str(source_candidate.get("email") or "").strip().lower()
        source_name = str(source_candidate.get("name") or "").strip() or "Unknown Candidate"

        if source_email and not _is_synthetic_email(source_email):
            existing = await self.supabase.table("candidates") \
                .select("id") \
                .eq("requisition_id", target_requisition_id) \
                .eq("email", source_email) \
                .is_("deleted_at", "null") \
                .limit(1) \
                .execute_async()
            existing_row = _first_row(existing.data)
            if existing_row:
                return str(existing_row["id"]), False

        target_email = source_email
        if not target_email or _is_synthetic_email(target_email):
            target_email = f"unknown+{source_candidate_round_id}@untracked.local"

        existing_by_target_email = await self.supabase.table("candidates") \
            .select("id") \
            .eq("requisition_id", target_requisition_id) \
            .eq("email", target_email) \
            .is_("deleted_at", "null") \
            .limit(1) \
            .execute_async()
        existing_target_row = _first_row(existing_by_target_email.data)
        if existing_target_row:
            return str(existing_target_row["id"]), False

        candidate_service = get_candidate_service()
        try:
            add_result = await candidate_service.add_candidate(
                requisition_id=target_requisition_id,
                org_id=org_id,
                name=source_name,
                email=target_email,
            )
            candidate_row = add_result.get("candidate") if isinstance(add_result, dict) else None
            candidate_id = candidate_row.get("id") if isinstance(candidate_row, dict) else None
            if not candidate_id:
                raise RuntimeError("Failed to create target candidate")
            return str(candidate_id), True
        except ValueError as exc:
            if "already exists" not in str(exc).lower():
                raise
        except Exception as exc:
            if not _is_unique_violation(exc):
                raise

        recheck = await self.supabase.table("candidates") \
            .select("id") \
            .eq("requisition_id", target_requisition_id) \
            .eq("email", target_email) \
            .is_("deleted_at", "null") \
            .limit(1) \
            .execute_async()
        row = _first_row(recheck.data)
        if row:
            return str(row["id"]), False
        raise RuntimeError("Failed to resolve target candidate")

    async def _copy_transcript_record(
        self,
        source_candidate_round_id: str,
        target_candidate_round_id: str,
        fallback_transcript_url: Optional[str] = None,
        fallback_duration_seconds: Optional[float] = None,
        fallback_participants=None,
    ) -> None:
        transcript_result = await self.supabase.table("transcripts") \
            .select(
                "recall_transcript_id, provider, full_text, segments, raw_transcript_url, "
                "word_count, duration_seconds, language, processed_at, feedback_transcript, participant_metadata"
            ) \
            .eq("candidate_round_id", source_candidate_round_id) \
            .limit(1) \
            .execute_async()

        transcript = _first_row(transcript_result.data)
        if transcript:
            copy_payload = {
                "candidate_round_id": target_candidate_round_id,
                "recall_transcript_id": transcript.get("recall_transcript_id"),
                "provider": transcript.get("provider") or "recallai",
                "full_text": transcript.get("full_text"),
                "segments": transcript.get("segments"),
                "raw_transcript_url": transcript.get("raw_transcript_url"),
                "word_count": transcript.get("word_count"),
                "duration_seconds": transcript.get("duration_seconds"),
                "language": transcript.get("language") or "en",
                "processed_at": transcript.get("processed_at"),
                "feedback_transcript": transcript.get("feedback_transcript"),
                "participant_metadata": transcript.get("participant_metadata"),
            }
        elif fallback_transcript_url:
            fallback_segments = await self._download_transcript_segments(fallback_transcript_url)
            if not fallback_segments:
                return
            copy_payload = {
                "candidate_round_id": target_candidate_round_id,
                "provider": "recallai",
                "segments": fallback_segments,
                "raw_transcript_url": fallback_transcript_url,
                "duration_seconds": fallback_duration_seconds,
                "language": "en",
                "processed_at": _now_iso(),
                "participant_metadata": fallback_participants,
            }
        else:
            return

        await self.supabase.table("transcripts") \
            .upsert(copy_payload, on_conflict="candidate_round_id") \
            .execute_async()

    async def _download_transcript_segments(self, transcript_url: str) -> Optional[list]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(transcript_url)
            if response.status_code != 200:
                logger.warning(
                    "untracked_import.transcript_fetch_failed status=%s url=%s",
                    response.status_code,
                    transcript_url,
                )
                return None
            payload = response.json()
            return payload if isinstance(payload, list) else None
        except Exception as exc:
            logger.warning(
                "untracked_import.transcript_fetch_exception url=%s error=%s",
                transcript_url,
                str(exc)[:200],
            )
            return None
