"""Provider-agnostic scorecards/evaluations port — a capability unified lacks."""

from typing import Protocol

from app.integrations.ats.core.models import AtsScorecard


class ScorecardsPort(Protocol):
    async def fetch_scorecards(
        self, application_id: str, candidate_id: str
    ) -> list[AtsScorecard]: ...
