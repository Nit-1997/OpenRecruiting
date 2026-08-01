from src.service.handlers.base_handler import BaseHandler
from src.service.handlers.feedback_handler import FeedbackHandler
from src.service.handlers.plan_handler import PlanHandler
from src.service.handlers.decision_handler import DecisionHandler
from src.service.handlers.question_summary_handler import QuestionSummaryHandler
from src.service.handlers.intake_handler import IntakeHandler
from src.service.handlers.intake_v2_handler import IntakeV2Handler
from src.service.handlers.feedback_debrief_handler import FeedbackDebriefHandler
from src.service.handlers.interview_handler import InterviewHandler
from src.service.handlers.jd_handler import JDHandler
from src.service.handlers.recruiter_insight_handler import RecruiterInsightHandler
from src.service.handlers.candidate_profile_handler import CandidateProfileHandler
from src.service.handlers.candidate_evaluation_handler import CandidateEvaluationHandler


class EventRouter:
    def __init__(
        self,
        feedback_handler: FeedbackHandler,
        plan_handler: PlanHandler,
        decision_handler: DecisionHandler,
        question_summaries_available: QuestionSummaryHandler | None = None,
        intake_transcript_available: IntakeHandler | None = None,
        feedback_debrief_available: FeedbackDebriefHandler | None = None,
        interview_transcript_available: InterviewHandler | None = None,
        jd_available: JDHandler | None = None,
        intake_v2_completed: IntakeV2Handler | None = None,
        recruiter_insight: RecruiterInsightHandler | None = None,
        candidate_profile_enriched: CandidateProfileHandler | None = None,
        candidate_evaluation: CandidateEvaluationHandler | None = None,
    ):
        self._handlers: dict[str, BaseHandler] = {
            "feedback_completed": feedback_handler,
            "plan_created": plan_handler,
            "decision_made": decision_handler,
        }
        if question_summaries_available:
            self._handlers["question_summaries_available"] = question_summaries_available
        if intake_transcript_available:
            self._handlers["intake_transcript_available"] = intake_transcript_available
        if feedback_debrief_available:
            self._handlers["feedback_debrief_available"] = feedback_debrief_available
        if interview_transcript_available:
            self._handlers["interview_transcript_available"] = interview_transcript_available
        if jd_available:
            self._handlers["jd_available"] = jd_available
        if intake_v2_completed:
            self._handlers["intake_v2_completed"] = intake_v2_completed
        if recruiter_insight:
            self._handlers["recruiter_insight"] = recruiter_insight
        if candidate_profile_enriched:
            self._handlers["candidate_profile_enriched"] = candidate_profile_enriched
        if candidate_evaluation:
            self._handlers["candidate_evaluation"] = candidate_evaluation

    def get_handler(self, event_type: str) -> BaseHandler | None:
        return self._handlers.get(event_type)

    @property
    def supported_events(self) -> list[str]:
        return list(self._handlers.keys())
