"""Ashby native ScorecardsPort — applicationFeedback.list → canonical scorecards.

Field names per Ashby docs; verify against a real seeded scorecard (live-shape gate
in the plan). `submittedValues` is a {path: value} dict; the 'Overall Recommendation'
ValueSelect (path `overall_recommendation`) carries the overall recommendation.

The `_OVERALL_TITLES` title-text heuristic is the part most likely to miss on real
data — if the live form's overall field is titled differently (e.g. "Hiring
Recommendation"/"Verdict"), it will land in `attributes` and `recommendation` stays
None; re-confirm the overall-field title against a real scorecard."""

from app.integrations.ats.core.models import AtsScorecard, AtsScorecardAttribute
from app.integrations.ats.unified_knit.transport import KnitTransport

_OVERALL_PATHS = {"overall_recommendation"}
_OVERALL_TITLES = {"overall recommendation", "recommendation", "overall"}


class AshbyScorecardsAdapter:
    def __init__(self, transport: KnitTransport, integration_id: str) -> None:
        self._t = transport
        self._iid = integration_id

    async def fetch_scorecards(self, application_id: str, candidate_id: str) -> list[AtsScorecard]:
        body = await self._t.passthrough(
            self._iid, "POST", "/applicationFeedback.list", {"applicationId": application_id}
        )
        raw = (body or {}).get("results")
        results = raw if isinstance(raw, list) else []
        return [self._map(item) for item in results if isinstance(item, dict)]

    @staticmethod
    def _map(item: dict) -> AtsScorecard:
        form = item.get("formDefinition") or {}
        fields_by_path: dict = {}
        for section in (form.get("sections") or []):
            for f in (section.get("fields") or []):
                fl = f.get("field") or {}
                path = fl.get("path")
                if path:
                    fields_by_path[path] = fl

        submitted = item.get("submittedValues")
        recommendation = None
        attributes: list[AtsScorecardAttribute] = []
        if isinstance(submitted, dict):
            for path, value in submitted.items():
                meta = fields_by_path.get(path) or {}
                title = (meta.get("title") or path or "").strip() or "Unnamed"
                if path in _OVERALL_PATHS or title.lower() in _OVERALL_TITLES:
                    recommendation = value
                    continue
                attributes.append(AtsScorecardAttribute(
                    name=title, rating=value, note=None, type=meta.get("type"),
                ))

        user = item.get("submittedByUser") or {}
        interviewer_name = " ".join(
            p for p in (user.get("firstName"), user.get("lastName")) if p
        ).strip() or None
        return AtsScorecard(
            id=item.get("id"),
            interviewer_id=user.get("id"),
            interviewer_name=interviewer_name,
            recommendation=recommendation,
            submitted_at=item.get("submittedAt"),
            interview_id=item.get("interviewEventId"),
            attributes=attributes,
        )
