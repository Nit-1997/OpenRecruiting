"""Canonical ATS models — the only shapes consumers (routers/services/FE)
ever see. Provider wire models map INTO these."""

from app.integrations.ats.core.models.candidates import (
    AtsApplication,
    AtsAttachment,
    AtsCandidate,
    AtsContactPoint,
    AtsQuestionResponse,
    AtsRejection,
    AtsStageRef,
    CandidateSearchCriteria,
)
from app.integrations.ats.core.models.common import Page
from app.integrations.ats.core.models.interviews import (
    AtsInterview,
    AtsInterviewer,
    AtsInterviewStage,
    AtsTranscript,
)
from app.integrations.ats.core.models.jobs import (
    AtsDepartment,
    AtsJob,
    AtsJobCreate,
    AtsOffice,
    AtsStage,
    AtsTeamMember,
)
from app.integrations.ats.core.models.scorecards import (
    AtsScorecard,
    AtsScorecardAttribute,
)

__all__ = [
    "AtsApplication",
    "AtsAttachment",
    "AtsCandidate",
    "AtsContactPoint",
    "AtsQuestionResponse",
    "AtsDepartment",
    "AtsInterview",
    "AtsInterviewer",
    "AtsInterviewStage",
    "AtsJob",
    "AtsJobCreate",
    "AtsOffice",
    "AtsRejection",
    "AtsScorecard",
    "AtsScorecardAttribute",
    "AtsStage",
    "AtsStageRef",
    "AtsTeamMember",
    "AtsTranscript",
    "CandidateSearchCriteria",
    "Page",
]
