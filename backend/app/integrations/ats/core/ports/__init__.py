"""Category ports — the interfaces every ATS provider implements."""

from app.integrations.ats.core.ports.candidates import CandidatesPort
from app.integrations.ats.core.ports.interviews import InterviewsPort
from app.integrations.ats.core.ports.jobs import JobsPort
from app.integrations.ats.core.ports.scorecards import ScorecardsPort

__all__ = ["CandidatesPort", "InterviewsPort", "JobsPort", "ScorecardsPort"]
