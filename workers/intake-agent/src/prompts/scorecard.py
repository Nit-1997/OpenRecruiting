ROUNDS_JSON_SCHEMA = """{
  "rounds": [
    {
      "name": "string (round name)",
      "category": "string (coding|design|behavioral|domain|culture|assessment)",
      "duration_minutes": "integer (30-60)",
      "description": "string (1-2 sentence overview)",
      "skills": ["string", "string", "..."],
      "openrecruiting_screenable": "boolean (true if a voice agent can run this round)",
      "openrecruiting_screenable_reason": "string (one sentence justifying openrecruiting_screenable)"
    }
  ]
}"""

ROUND_DETAILS_JSON_SCHEMA = """{
  "guidelines": [
    {"title": "string", "description": "string"}
  ],
  "feedback_questions": [
    {"heading": "string (2-4 word competency label)", "description": "string (one short sentence, under 20 words)"}
  ]
}"""


def build_rounds_prompt(
    intake_summary: str,
) -> str:
    return f"""You are an expert interview designer creating interview round skeletons.

You have two inputs:
1. A knowledge base of interview best practices provided in the system context
2. A structured intake summary from an intake call

<intake_summary>
{intake_summary}
</intake_summary>

Using the knowledge base as your guide for best practices and the intake summary for role-specific context, design the interview rounds (skeletons only — no guidelines or feedback questions).

For each interview round:

1. **Round Name**: Clear, descriptive name (e.g. "Resume Screen & Hiring Manager Interview", "Panel Presentation", "Problem Solving")
2. **Category**: One of: coding, design, behavioral, domain, culture, assessment
3. **Duration**: In minutes (typically 30-60)
4. **Description**: 1-2 sentence overview of what this round evaluates
5. **Skills**: List of 3-6 specific skills evaluated in this round

For each round, set "openrecruiting_screenable": true ONLY when the round is an actual early recruiter-style SCREEN that OpenRecruiting can run by voice — i.e. a recruiter screen, phone/initial screen, or intro call, OR the FIRST round when it is conversational (culture / behavioral / motivation fit). Set "openrecruiting_screenable": false for everything else, including: later behavioral or "hiring manager" rounds (round 2+), technical or domain deep-dives, coding, system design, design exercises, take-home, whiteboard, and case studies. A behavioral panel that is not the first round is NOT a screen. Add a one-sentence "openrecruiting_screenable_reason".

Design Principles:
- Each round should have a distinct focus — minimize overlap between rounds
- Skills should be specific and measurable, not generic
- The overall plan should cover technical depth, problem-solving, communication, and culture fit
- Prefer 3-5 rounds total unless the intake summary specifies otherwise

Output ONLY valid JSON matching this exact schema — no markdown, no explanation, no wrapping:

{ROUNDS_JSON_SCHEMA}

Rules:
- category must be one of: coding, design, behavioral, domain, culture, assessment
- duration_minutes must be an integer between 15 and 120
- skills must be a non-empty array of strings
- Do not include guidelines or feedback_questions
- Do not include any text outside the JSON object
- Do not wrap in markdown code blocks"""


def build_round_details_prompt(
    round_skeleton: dict,
    intake_summary: str,
) -> str:
    import json
    skeleton_str = json.dumps(round_skeleton, indent=2)

    return f"""You are an expert interview designer. Generate interviewer guidelines and feedback evaluation questions for a single interview round.

Use the knowledge base provided in the system context for best practices.

<round>
{skeleton_str}
</round>

<intake_summary>
{intake_summary}
</intake_summary>

Generate:
1. **Guidelines**: 2-4 actionable interviewer guidelines (title + description) for conducting this round effectively
2. **Feedback Questions**: Exactly 3 evaluation questions. Each question should:
   - Have a SHORT heading — 2-4 words max, just the competency label (e.g. "Code Quality", "Leadership", "Product Ownership", "Trade-off Analysis")
   - Have a BRIEF description — one short sentence describing what to evaluate, under 20 words (e.g. "Readability, structure, and maintainability of the code written")
   - Do NOT include sub-questions, bullet points, or "Consider:" prompts in the description
   - Do NOT start descriptions with "How effectively..." or "How well..."

CRITICAL FORMATTING RULES FOR FEEDBACK QUESTIONS:
- Heading: A concise competency label. GOOD: "Global Maturity", "Code Quality". BAD: "Structured Problem-Solving & Frameworks"
- Description: One short evaluative sentence. GOOD: "Approach to identifying and managing architectural trade-offs in complex ecosystems". BAD: "How effectively did the candidate apply design thinking principles? Consider: Did they define the problem space?"

Output ONLY valid JSON matching this exact schema — no markdown, no explanation, no wrapping:

{ROUND_DETAILS_JSON_SCHEMA}

Rules:
- guidelines must be a non-empty array of objects with title and description (2-4 items)
- feedback_questions must have exactly 3 items
- feedback_questions heading: 2-4 word competency label. Shorten any long headings.
- feedback_questions description: one short sentence, MAX 20 words. Strip any sub-questions or "Consider:" prompts.
- Do not include any text outside the JSON object
- Do not wrap in markdown code blocks"""
