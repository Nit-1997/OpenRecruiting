"""Provider-agnostic interviews port — interview events, their transcripts, and
a job's interview-plan stages. A capability unified Knit lacks (interview detail
is always a native pull)."""

from typing import Protocol, runtime_checkable

from app.integrations.ats.core.models import (
    AtsInterview,
    AtsInterviewStage,
    AtsTranscript,
)


@runtime_checkable
class InterviewsPort(Protocol):
    async def fetch_interviews(self, application_id: str) -> list[AtsInterview]: ...

    async def fetch_transcript(
        self, notetaker_transcript_id: str
    ) -> AtsTranscript | None: ...

    async def fetch_job_stages(self, job_id: str) -> list[AtsInterviewStage]: ...
