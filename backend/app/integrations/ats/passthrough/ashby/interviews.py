"""Ashby native InterviewsPort — interviewSchedule.list → AtsInterview[], enriched
with stage titles (interviewStage.list) and interview titles (interview.list),
both fetched once per call and cached. fetch_transcript → notetakerTranscript.info.

interviewSchedule.list has no confirmed applicationId filter param (spec §3), so
we list-all and filter client-side. Meeting URL is opportunistic (see mapping)."""

from app.integrations.ats.core.models import (
    AtsInterview,
    AtsInterviewStage,
    AtsTranscript,
)
from app.integrations.ats.passthrough.ashby.interviews_mapping import (
    interviews_from_schedule,
    stage_from_wire,
    transcript_from_wire,
)
from app.integrations.ats.unified_knit.transport import KnitTransport


def _results_list(body: dict | None) -> list:
    raw = (body or {}).get("results")
    return raw if isinstance(raw, list) else []


def _results_obj(body: dict | None) -> dict:
    raw = (body or {}).get("results")
    return raw if isinstance(raw, dict) else {}


class AshbyInterviewsAdapter:
    def __init__(self, transport: KnitTransport, integration_id: str) -> None:
        self._t = transport
        self._iid = integration_id
        # Per-instance memo of the static catalogs. The reconcile sweep reuses ONE
        # adapter instance per connection per tick and calls fetch_interviews up to
        # 100x; without this each call re-fetched interviewSchedule.list (full
        # org list-all) + the stage/interview title maps. Cached on the INSTANCE
        # only (fresh per tick / per get_ats_provider), never across the process.
        self._schedules_cache: list | None = None
        self._stage_titles_cache: dict[str, str] | None = None
        self._interview_titles_cache: dict[str, str] | None = None

    async def _all_schedules(self) -> list:
        if self._schedules_cache is None:
            body = await self._t.passthrough(
                self._iid, "POST", "/interviewSchedule.list", {}
            )
            self._schedules_cache = _results_list(body)
        return self._schedules_cache

    async def _stage_titles(self) -> dict[str, str]:
        if self._stage_titles_cache is None:
            self._stage_titles_cache = await self._stage_title_map()
        return self._stage_titles_cache

    async def _interview_titles(self) -> dict[str, str]:
        if self._interview_titles_cache is None:
            self._interview_titles_cache = await self._title_map("/interview.list")
        return self._interview_titles_cache

    async def _title_map(self, path: str) -> dict[str, str]:
        body = await self._t.passthrough(self._iid, "POST", path, {})
        out: dict[str, str] = {}
        for item in _results_list(body):
            if isinstance(item, dict) and item.get("id") and item.get("title"):
                out[item["id"]] = item["title"]
        return out

    async def _stage_title_map(self) -> dict[str, str]:
        # interviewStage.list REQUIRES interviewPlanId (it is NOT a list-all endpoint),
        # so enumerate plans first, then list each plan's stages. Verified live against
        # the Ashby sandbox: a bare interviewStage.list 400s with "interviewPlanId ... undefined".
        plans = await self._t.passthrough(
            self._iid, "POST", "/interviewPlan.list", {}
        )
        out: dict[str, str] = {}
        for plan in _results_list(plans):
            if not (isinstance(plan, dict) and plan.get("id")):
                continue
            stages = await self._t.passthrough(
                self._iid,
                "POST",
                "/interviewStage.list",
                {"interviewPlanId": plan["id"]},
            )
            for item in _results_list(stages):
                if isinstance(item, dict) and item.get("id") and item.get("title"):
                    out[item["id"]] = item["title"]
        return out

    async def fetch_interviews(self, application_id: str) -> list[AtsInterview]:
        schedules = [
            s
            for s in await self._all_schedules()
            if isinstance(s, dict) and s.get("applicationId") == application_id
        ]
        if not schedules:
            return []
        # Enrich from the per-instance caches (each catalog fetched once, reused
        # across every fetch_interviews call within this tick), only when there's
        # matching work.
        stage_titles = await self._stage_titles()
        interview_titles = await self._interview_titles()
        out: list[AtsInterview] = []
        for schedule in schedules:
            out.extend(
                interviews_from_schedule(schedule, stage_titles, interview_titles)
            )
        return out

    async def fetch_transcript(
        self, notetaker_transcript_id: str
    ) -> AtsTranscript | None:
        body = await self._t.passthrough(
            self._iid,
            "POST",
            "/notetakerTranscript.info",
            {"notetakerTranscriptId": notetaker_transcript_id},
        )
        return transcript_from_wire((body or {}).get("results"), source="notetaker")

    async def _plan_ids_for_job(self, job_id: str) -> list[str]:
        """Resolve a job's interview-plan id(s). interviewStage.list REQUIRES an
        interviewPlanId (live-confirmed), so we discover plans by job first:
        jobInterviewPlan.info {jobId} (returns the job's plan rows), falling back
        to job.info {id} (interviewPlanIds / defaultInterviewPlanId)."""
        ids: list[str] = []

        plan_info = await self._t.passthrough(
            self._iid, "POST", "/jobInterviewPlan.info", {"jobId": job_id}
        )
        for plan in _results_list(plan_info):
            if isinstance(plan, dict) and plan.get("id"):
                ids.append(str(plan["id"]))
        # jobInterviewPlan.info may instead return a single plan object.
        plan_obj = _results_obj(plan_info)
        if plan_obj.get("id"):
            ids.append(str(plan_obj["id"]))

        if not ids:
            job_info = await self._t.passthrough(
                self._iid, "POST", "/job.info", {"id": job_id}
            )
            job_obj = _results_obj(job_info)
            for pid in job_obj.get("interviewPlanIds") or []:
                if pid:
                    ids.append(str(pid))
            default_pid = job_obj.get("defaultInterviewPlanId")
            if default_pid:
                ids.append(str(default_pid))

        # De-dup, preserve first-seen order.
        seen: set[str] = set()
        unique: list[str] = []
        for pid in ids:
            if pid not in seen:
                seen.add(pid)
                unique.append(pid)
        return unique

    async def fetch_job_stages(self, job_id: str) -> list[AtsInterviewStage]:
        """A job's interview-plan stages (all types; caller filters to Active).

        Returns canonical AtsInterviewStage rows across the job's plan(s)."""
        plan_ids = await self._plan_ids_for_job(job_id)
        out: list[AtsInterviewStage] = []
        for plan_id in plan_ids:
            stages = await self._t.passthrough(
                self._iid, "POST", "/interviewStage.list", {"interviewPlanId": plan_id}
            )
            for item in _results_list(stages):
                stage = stage_from_wire(item, fallback_plan_id=plan_id)
                if stage is not None:
                    out.append(stage)
        return out
