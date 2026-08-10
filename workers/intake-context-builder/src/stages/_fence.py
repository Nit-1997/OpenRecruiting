"""Strip a markdown code fence from a model reply.

Both JSON-returning stages need this and only one had it. `synthesize` carried a
private copy; `parse_jd` did not, so when the model wrapped its object in
```json — which it does, verified live against context-parse-jd — json.loads
failed, facts came back empty, and the JD contributed NOTHING to the intake
context. The stage logged "unparseable" and the pipeline carried on, so the only
symptom was a thinner intake than the recruiter's JD warranted.

Shared here rather than duplicated so the next JSON stage cannot be written
without it.
"""

from __future__ import annotations


def strip_markdown_fence(raw: str) -> str:
    """Strip leading ```json / ``` and trailing ``` if the model wrapped the body."""
    if not raw.startswith("```"):
        return raw
    first_newline = raw.find("\n")
    if first_newline == -1:
        return raw
    body = raw[first_newline + 1:]
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -len("```")]
    return body.strip()
