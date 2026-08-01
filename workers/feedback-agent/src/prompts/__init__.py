from .participant_detection import PROMPT as PARTICIPANT_DETECTION_PROMPT
from .topic_mapping import PROMPT as TOPIC_MAPPING_PROMPT
from .feedback_extract import PROMPT as FEEDBACK_EXTRACT_PROMPT
from .feedback_condense import PROMPT as FEEDBACK_CONDENSE_PROMPT
from .evidence_extraction import PROMPT as EVIDENCE_EXTRACTION_PROMPT
from .judge import PROMPT as JUDGE_PROMPT
from .question_summary import PROMPT as QUESTION_SUMMARY_PROMPT
from .round_summary import PROMPT as ROUND_SUMMARY_PROMPT
from .verdict_extraction import PROMPT as VERDICT_EXTRACTION_PROMPT

__all__ = [
    "PARTICIPANT_DETECTION_PROMPT",
    "TOPIC_MAPPING_PROMPT",
    "FEEDBACK_EXTRACT_PROMPT",
    "FEEDBACK_CONDENSE_PROMPT",
    "EVIDENCE_EXTRACTION_PROMPT",
    "JUDGE_PROMPT",
    "QUESTION_SUMMARY_PROMPT",
    "ROUND_SUMMARY_PROMPT",
    "VERDICT_EXTRACTION_PROMPT",
]


def format_prompt(name: str, **kwargs) -> str:
    """Format a prompt template with the given parameters."""
    prompts = {
        "participant_detection": PARTICIPANT_DETECTION_PROMPT,
        "topic_mapping": TOPIC_MAPPING_PROMPT,
        "feedback_extract": FEEDBACK_EXTRACT_PROMPT,
        "feedback_condense": FEEDBACK_CONDENSE_PROMPT,
        "evidence_extraction": EVIDENCE_EXTRACTION_PROMPT,
        "judge": JUDGE_PROMPT,
        "question_summary": QUESTION_SUMMARY_PROMPT,
        "round_summary": ROUND_SUMMARY_PROMPT,
        "verdict_extraction": VERDICT_EXTRACTION_PROMPT,
    }

    template = prompts.get(name)
    if template is None:
        raise ValueError(f"Unknown prompt: {name}")

    return template.format(**kwargs)
