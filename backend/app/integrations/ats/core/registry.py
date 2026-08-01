"""Resolve an organization's active ATS connection to a provider bundle.

This is the single composition point where core meets providers: today every
connection routes to unified_knit; phase 2+ adds per-provider passthrough
selection here (and ONLY here)."""

from dataclasses import dataclass

from app.integrations.ats.core.errors import AtsNotConnectedError
from app.integrations.ats.core.ports import (
    CandidatesPort,
    InterviewsPort,
    JobsPort,
    ScorecardsPort,
)
from app.integrations.ats.passthrough.ashby.candidates import AshbyCandidatesAdapter
from app.integrations.ats.passthrough.ashby.interviews import AshbyInterviewsAdapter
from app.integrations.ats.passthrough.ashby.scorecards import AshbyScorecardsAdapter
from app.integrations.ats.passthrough.workable.candidates import WorkableCandidatesAdapter
from app.integrations.ats.passthrough.workable.scorecards import WorkableScorecardsAdapter
from app.integrations.ats.unified_knit.apis.candidates.api import KnitCandidatesApi
from app.integrations.ats.unified_knit.apis.jobs.api import KnitJobsApi
from app.integrations.ats.unified_knit.transport import get_knit_transport


@dataclass(slots=True)
class AtsProviderBundle:
    connection_id: str
    provider: str
    knit_integration_id: str
    jobs: JobsPort
    candidates: CandidatesPort
    scorecards: ScorecardsPort | None = None
    interviews: InterviewsPort | None = None


async def get_ats_provider(supabase, organization_id: str) -> AtsProviderBundle:
    result = await (
        supabase.table("ats_connections")
        .select("id, provider, knit_integration_id")
        .eq("organization_id", str(organization_id))
        .eq("status", "active")
        .limit(1)
        .execute_async()
    )
    if not result.data:
        raise AtsNotConnectedError(
            f"org {organization_id} has no active ATS connection"
        )
    row = result.data[0]
    transport = get_knit_transport()
    integration_id = row["knit_integration_id"]
    provider = row["provider"]

    scorecards: ScorecardsPort | None = None
    interviews: InterviewsPort | None = None
    if provider == "ashby":
        candidates: CandidatesPort = AshbyCandidatesAdapter(transport, integration_id)
        scorecards = AshbyScorecardsAdapter(transport, integration_id)
        interviews = AshbyInterviewsAdapter(transport, integration_id)
    elif provider == "workable":
        candidates = WorkableCandidatesAdapter(transport, integration_id)
        scorecards = WorkableScorecardsAdapter(transport, integration_id)
    else:
        candidates = KnitCandidatesApi(transport, integration_id)

    return AtsProviderBundle(
        connection_id=row["id"],
        provider=provider,
        knit_integration_id=integration_id,
        jobs=KnitJobsApi(transport, integration_id),
        candidates=candidates,
        scorecards=scorecards,
        interviews=interviews,
    )
