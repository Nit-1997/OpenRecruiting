PROMPT = """# Feedback Condensation

Condense raw feedback bullets for ONE topic into a small set of clean,
opposed pairs (feedback + semantic negation), preserving sub-skill
distinctions.

## INPUT

TOPIC: {topic_heading}
TOPIC DESCRIPTION: {topic_description}

RAW BULLETS (with the surrounding monologue context that grounds them):
{bullets_with_context}

Each raw bullet shows its strength tag in brackets [primary] or [passing]
right after the bullet text. Use these as the input strength values for
your merge logic in Rule 6.

## RULES

1. **Preserve sub-skill granularity. DO NOT merge bullets about different
   sub-skills under the same topic.**

   For example, under "Live Adaptability":
   - "communication clarity after coaching feedback" (sub-skill A)
   - "speed of pivot when redirected to a hypothetical" (sub-skill B)

   These are DIFFERENT sub-skills. Keep them as separate bullets even
   though both fall under Adaptability.

2. When MERGING bullets that ARE about the same sub-skill (e.g., the
   interviewer said the same thing twice in slightly different words),
   write a SINGLE coherent source_context that captures the through-line.
   Do NOT concatenate the two source_contexts into a bag of disjoint
   sentences. The merged source_context must describe a single coherent
   moment or sub-skill.

3. Produce a semantic antifeedback (the polar opposite of the
   feedback) for each condensed bullet. The antifeedback MUST:
   - Address the SAME sub-skill the feedback addresses; only the
     polarity flips.
   - Be a substantive, testable claim, not a generic negation. "Did
     not show strong ownership" is too vague. Instead: "Did not
     demonstrate end-to-end ownership of a complex feature, deferring
     decisions to others." Specificity matters because downstream
     stages search transcript chunks for evidence of this claim; a
     weak antifeedback produces noisy or absent counter-evidence.
   - If the feedback is neutral sentiment (a balanced observation,
     not a strength or gap), set "antifeedback_bullet" to an empty
     string. There is no clean polar opposite of a neutral observation
     and a fabricated one will mislead downstream stages.

4. Preserve sentiment.

5. Hard cap at 6 condensed bullets per topic. Merge only true
   duplicates; do not force-merge distinct sub-skills to hit a lower
   target. If more than 6 distinct sub-skills exist, drop the weakest
   "passing" observations first.

6. When merging bullets, set claim_strength to the STRONGEST input. If any
   merged input was "primary", the result is "primary". Two passing bullets
   merging produce a passing bullet.

## LENGTH CAPS

- "feedback_bullet" and "antifeedback_bullet" each at most 25 words.
- "source_context" at most 60 words.

## FORMATTING

Do NOT use em dashes (—) or double-hyphens (--) anywhere in the output
text, including "feedback_bullet", "antifeedback_bullet", and
"source_context". Use commas, colons, semicolons, or split into a new
sentence instead.

## OUTPUT

Return ONLY a JSON object with the exact shape below. No prose, no
markdown fences, no preamble, no trailing commentary.

{{
  "condensed_feedback": [
    {{
      "feedback_bullet": "condensed claim (no [+]/[-] marker)",
      "antifeedback_bullet": "semantic negation (empty string if feedback is neutral)",
      "sentiment": "positive | negative | neutral",
      "source_context": "through-line source context: single coherent passage",
      "claim_strength": "primary | passing"
    }}
  ]
}}
"""
