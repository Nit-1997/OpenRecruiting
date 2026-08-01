"""The 9 intake questions, versioned for forward-compat per session."""

from copy import deepcopy
from typing import Final

QUESTIONS_VERSION: Final[str] = "v1-2026-05-27"

INTAKE_QUESTIONS: Final[list[dict]] = [
    {
        "id": "q1_role_overview",
        "order": 1,
        "topic": "Role Overview & Key Responsibilities",
        "default_text": "What does someone in this role actually do day-to-day? What are the top 3 responsibilities?",
    },
    {
        "id": "q2_rounds",
        "order": 2,
        "topic": "Interview Rounds",
        "default_text": "How many interview rounds do you envision, and what types of interviews will they be?",
    },
    {
        "id": "q3_focus_areas",
        "order": 3,
        "topic": "Interview Focus Areas",
        "default_text": "What specific areas should the interview rounds focus on? Any particular scenarios or problems you'd like candidates to solve?",
    },
    {
        "id": "q4_must_haves",
        "order": 4,
        "topic": "Must-Have Skills & Experience",
        "default_text": "What are the absolute must-haves in terms of skills, tools, or experience?",
    },
    {
        "id": "q5_nice_to_haves",
        "order": 5,
        "topic": "Nice-to-Have Skills",
        "default_text": "Are there any nice-to-haves that would set a candidate apart?",
    },
    {
        "id": "q6_cultural_fit",
        "order": 6,
        "topic": "Cultural Fit & Soft Skills",
        "default_text": "What kind of personality or working style thrives in this role and on this team?",
    },
    {
        "id": "q7_team_structure",
        "order": 7,
        "topic": "Team Structure",
        "default_text": "Who are the key stakeholders they will interact with and what does their team look like?",
    },
    {
        "id": "q8_red_flags",
        "order": 8,
        "topic": "Red Flags & Deal-Breakers",
        "default_text": "What are the red flags or deal-breakers you've seen in past candidates?",
    },
    {
        "id": "q9_anything_else",
        "order": 9,
        "topic": "Anything Else",
        "default_text": "Is there anything else about this role that you think is important for designing the interview plan?",
    },
]


def snapshot_questions() -> list[dict]:
    """Return a deep copy of the questions list — safe to mutate, safe to JSON-serialize."""
    return deepcopy(INTAKE_QUESTIONS)
