"""
Transforms pipeline results into database format.

This is the SINGLE SOURCE OF TRUTH for converting pipeline results into the format
expected by the database. Used by both local API and production Lambda.
"""

from src.logging import get_logger

logger = get_logger(__name__)


def transform_to_feedback_output(
    judge_result: dict,
    summary_result: dict | None = None,
) -> dict:
    """
    Transform pipeline results into database-ready feedback_output.

    Args:
        judge_result: Raw output from JudgeService containing judged_feedback list
        summary_result: Output from SummaryService containing question_summaries,
                       round_summary, competency_snapshots, and round_rating

    Returns:
        dict with round_rating, round_summary, competency_snapshots, question_summaries, and feedback_questions
    """
    if not isinstance(judge_result, dict):
        return {
            "round_rating": "maybe",
            "round_summary": "",
            "competency_snapshots": "",
            "question_summaries": {},
            "feedback_questions": [],
            "overall_feedback": [],
        }

    judged_feedback = judge_result.get("judged_feedback", [])

    if summary_result and isinstance(summary_result, dict):
        round_rating = summary_result.get("round_rating", "maybe")
        round_summary = summary_result.get("round_summary", "")
        competency_snapshots = summary_result.get("competency_snapshots", "")
        overall_feedback = summary_result.get("overall_feedback") or []

        raw_question_summaries = summary_result.get("question_summaries", [])
        logger.info(
            "transform_summary_input",
            has_summary_result=True,
            raw_question_summaries_count=len(raw_question_summaries),
            raw_question_summaries_type=type(raw_question_summaries).__name__,
            first_item_type=type(raw_question_summaries[0]).__name__ if raw_question_summaries else "none",
            first_item_sample=str(raw_question_summaries[0])[:200] if raw_question_summaries else "none",
        )

        question_summaries = {}
        for qs in raw_question_summaries:
            if isinstance(qs, dict):
                topic_id = qs.get("topic_id", "")
                if topic_id.startswith("T"):
                    try:
                        q_num = int(topic_id[1:])
                        question_summaries[q_num] = qs.get("summary", "")
                    except ValueError:
                        pass

        logger.info(
            "transform_summary_output",
            question_summaries_keys=list(question_summaries.keys()),
            question_summaries_count=len(question_summaries),
        )
    else:
        logger.warning(
            "transform_no_summary_result",
            summary_result_type=type(summary_result).__name__ if summary_result else "None",
            summary_result_truthy=bool(summary_result),
        )
        round_rating = "maybe"
        round_summary = ""
        competency_snapshots = ""
        question_summaries = {}
        overall_feedback = []

    feedback_output = {
        "round_rating": round_rating,
        "round_summary": round_summary,
        "competency_snapshots": competency_snapshots,
        "question_summaries": question_summaries,
        "feedback_questions": [],
    }

    feedback_by_question: dict[int, list] = {}

    for item in judged_feedback:
        if not isinstance(item, dict):
            continue
        topic_id = item.get("topic_id", "")

        if topic_id.startswith("T"):
            try:
                q_num = int(topic_id[1:])
            except ValueError:
                # T_OVERALL no longer flows through judge_result post-1.9;
                # any non-numeric T-prefixed id is defensively skipped.
                continue
            if q_num not in feedback_by_question:
                feedback_by_question[q_num] = []
            feedback_by_question[q_num].append({
                "feedback_data": item.get("feedback", ""),
                "evidence": item.get("evidence", []),
                "evidence_status": item.get("evidence_status", "none"),
                "claim_strength": item.get("claim_strength", "primary"),
            })

    for q_num, feedback_items in sorted(feedback_by_question.items()):
        feedback_output["feedback_questions"].append({
            "question_number": q_num,
            "feedback": feedback_items,
        })

    feedback_output["overall_feedback"] = overall_feedback

    return feedback_output


def transform_judge_result_to_feedback_output(judge_result: dict) -> dict:
    """
    Legacy function for backward compatibility.
    Prefer using transform_to_feedback_output with summary_result.
    """
    return transform_to_feedback_output(judge_result, None)
