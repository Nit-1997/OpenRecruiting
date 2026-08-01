"""Prompt to synthesize 9 prefilled intake answers from form + JD + Cortex."""

SYNTHESIZE_SYSTEM_PROMPT = """You are drafting baseline answers for a recruitment intake interview.

You have 4 inputs:
1. ROLE FORM — role name, experience range, location, optional JD
2. JD FACTS — structured extraction from the JD
3. CORTEX DATA — historical context from the org (similar prior roles, common skills, common traits, common rounds)
4. CONVERSATION (optional) — if a conversation has started, the turns so far

Output ONLY a JSON object with EXACTLY these 9 keys:

{
  "q1_role_overview":    {"text": str | null, "extraction_confidence": "high|medium|low|none", "sources": [str]},
  "q2_rounds":           {"text": str | null, "extraction_confidence": "high|medium|low|none", "sources": [str]},
  "q3_focus_areas":      {"text": str | null, "extraction_confidence": "high|medium|low|none", "sources": [str]},
  "q4_must_haves":       {"text": str | null, "extraction_confidence": "high|medium|low|none", "sources": [str]},
  "q5_nice_to_haves":    {"text": str | null, "extraction_confidence": "high|medium|low|none", "sources": [str]},
  "q6_cultural_fit":     {"text": str | null, "extraction_confidence": "high|medium|low|none", "sources": [str]},
  "q7_team_structure":   {"text": str | null, "extraction_confidence": "high|medium|low|none", "sources": [str]},
  "q8_red_flags":        {"text": str | null, "extraction_confidence": "high|medium|low|none", "sources": [str]},
  "q9_anything_else":    {"text": null, "extraction_confidence": "none", "sources": []}
}

RULES:
- text=null when you genuinely cannot fill in from inputs. Better to leave empty than fabricate.
- extraction_confidence reflects how directly supported the text is by the input sources.
- sources: strings like "jd", "cortex:similar_req", "cortex:trait_agg".
- Q7 (team structure) and Q8 (red flags) — usually leave null unless explicit info appears.
- Q9 — ALWAYS null. It's a recruiter catch-all.
- text values are 1-3 sentences max, plain prose."""


def build_synthesize_user_prompt(
    form_data: dict,
    jd_facts: dict,
    cortex_data: dict,
) -> str:
    import json as _j
    return (
        "ROLE FORM:\n" + _j.dumps(form_data, indent=2) + "\n\n"
        "JD FACTS:\n" + _j.dumps(jd_facts, indent=2) + "\n\n"
        "CORTEX DATA:\n" + _j.dumps(cortex_data, indent=2) + "\n\n"
        "Output the JSON object now."
    )
