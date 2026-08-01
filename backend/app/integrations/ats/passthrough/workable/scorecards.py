"""Workable native ScorecardsPort — interviewer evaluations from the activities
timeline (action=="rating": thumbs score + free-text body + member)."""

from app.integrations.ats.core.models import AtsScorecard
from app.integrations.ats.passthrough.workable.mapping import rating_activity_to_scorecard
from app.integrations.ats.unified_knit.transport import KnitTransport


class WorkableScorecardsAdapter:
    def __init__(self, transport: KnitTransport, integration_id: str) -> None:
        self._t = transport
        self._iid = integration_id

    async def fetch_scorecards(self, application_id: str, candidate_id: str) -> list[AtsScorecard]:
        resp = await self._t.passthrough(self._iid, "GET", f"/candidates/{candidate_id}/activities")
        activities = (resp or {}).get("activities") or []
        return [
            rating_activity_to_scorecard(a)
            for a in activities
            if isinstance(a, dict) and a.get("action") == "rating"
        ]
