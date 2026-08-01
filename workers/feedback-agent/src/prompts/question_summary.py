PROMPT = """# Per-Competency Summary

Write a tight, story-shaped summary of the candidate's performance on
this competency. The reader is a recruiter scanning the scorecard — they
need to understand the finding in 2-3 sentences, not read an essay.

## INPUTS

TOPIC: {topic_heading}

VERBAL VERDICT (interviewer's overall verdict on the candidate):
{verbal_verdict}

CLAIM:
{feedback}

EVIDENCE STATUS: {evidence_status}

EVIDENCE:
{evidence}

CLAIM STRENGTH: {claim_strength}

## RULES

1. Render the finding for the reader, not the system's verdict on it.
   The recruiter sees the evidence_status badge separately and can click
   to inspect the evidence. The prose must NOT narrate the status:
   - Do NOT write "the interviewer's claim is contradicted by the
     transcript", "this is contradicted", "the transcript shows otherwise",
     "calibrated by the transcript", "in tension with what was observed",
     or similar meta-commentary.
   - For supported claims: state the finding confidently.
   - For contradicted claims: state what the transcript actually showed
     about the candidate on this sub-skill — write the calibrated reality,
     not the calibration process.

2. VERBAL VERDICT shapes register only, not content.
   The verdict label adjusts *how* the summary reads (warmth, hedging,
   directness) but never *what* it asserts.

   - strong_yes / yes        : confident, direct register
   - maybe                   : balanced, neutral register
   - no / strong_no          : critical, plainspoken register
   - unknown / null / empty  : neutral register; do not infer a
                               verdict, lead with the finding as-is

   Do NOT add evaluative qualifiers like "coachable", "not disqualifying",
   "developmental", "worth watching", "blocking concern", "concerning
   pattern", "at this stage" unless those exact framings appear in the
   CLAIM or EVIDENCE. A positive overall verdict does not soften a
   critical per-topic claim; a negative overall verdict does not amplify
   a positive one. The topic summary stands on its own and reflects only
   the strength or weakness present in the CLAIM and EVIDENCE for THIS
   topic.

3. Ground the summary in the claim and evidence. Do not invent facts.
   Do not add a hiring recommendation. Do not reference the interviewer's
   overall stance ("the interviewer treats this as...", "the interviewer
   did not flag this as...") — that framing belongs in the round summary,
   not here.

4. No meta-language ("the candidate showed", "the evidence indicates").
   Write as a person would summarize: direct, specific, person-centered.

5. If claim_strength is "passing", this is a one-sentence aside from the
   interviewer, not a load-bearing assessment. Render it tersely or as a
   qualifier on a stronger claim from the same topic. Do NOT make it the
   centerpiece of the summary.

## LENGTH AND STYLE

- Hard cap: 3 sentences. Aim for 2.
- Each summary must read as a self-contained story: someone reading only
  this sentence, with no other context, should understand the finding,
  who it's about, and what made it notable.
- Be rich with specifics. Pull concrete details from the evidence:
  numbers, named projects, company names, decisions, outcomes. Generic
  abstractions ("strong ownership", "good communication") without
  specifics are not acceptable.
- Flowy, narrative prose. Sentences should connect naturally. Avoid
  bullet-style listing inside the sentence.
- Do NOT use em dashes (—) or double-hyphens (--) anywhere in the
  output. Use commas, colons, semicolons, or split into a new sentence
  instead.

## SENTIMENT — TRACK THE FINDING, NOT THE CLAIM

Emit a `finding_sentiment` field. This reflects the polarity of the
ACTUAL FINDING described in your summary, not the polarity of the
original interviewer claim. Use the table:

- EVIDENCE STATUS = supported, original claim positive   → "positive"
- EVIDENCE STATUS = supported, original claim negative   → "negative"
- EVIDENCE STATUS = supported, original claim neutral    → "neutral"
- EVIDENCE STATUS = contradicted, original claim positive → "negative"  (the positive claim did not hold up; the finding for the candidate is negative)
- EVIDENCE STATUS = contradicted, original claim negative → "positive"  (the negative claim did not hold up; the finding for the candidate is positive)
- EVIDENCE STATUS = contradicted, original claim neutral  → "neutral"

The downstream UI uses `finding_sentiment` to color the badge a
recruiter sees. The badge must match what the prose actually says
about the candidate.

## OUTPUT

Return ONLY a JSON object with the exact shape below. No prose, no
markdown fences, no preamble, no trailing commentary.

{{
  "summary": "2-3 sentence self-contained narrative",
  "finding_sentiment": "positive | negative | neutral"
}}
"""
