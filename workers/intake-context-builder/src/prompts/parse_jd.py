"""Prompt for parsing JD text into structured facts."""

PARSE_JD_SYSTEM_PROMPT = """You are extracting structured facts from a job description.
Return ONLY a JSON object with these keys (use empty arrays/strings if not present):

{
  "must_have_skills": [string],
  "nice_to_have_skills": [string],
  "responsibilities": [string],
  "team_signals": [string]
}

No prose. No markdown. Just the JSON object."""


def build_parse_jd_user_prompt(jd_text: str) -> str:
    return f"Job description:\n\n{jd_text[:30_000]}"  # truncate hard if huge
