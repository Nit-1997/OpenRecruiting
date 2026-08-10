"""Stage 2: parse JD into structured facts through the LLM gateway."""

from __future__ import annotations

import json
from typing import Any, Optional

import structlog

from ._fence import strip_markdown_fence
from ..prompts.parse_jd import PARSE_JD_SYSTEM_PROMPT, build_parse_jd_user_prompt

logger = structlog.get_logger(__name__)


async def parse_jd(
    llm: Any,
    model: str,
    jd_text: Optional[str],
) -> dict[str, Any]:
    """Parse a JD into structured facts. `model` is a gateway alias.

    `llm` is a provider-agnostic client with `.complete(...)`. The parameter was
    `anthropic_client` before phase 4 and was RENAMED rather than repurposed: a
    wrong object under the old name would have failed as an AttributeError on
    `.messages`, while a wrong keyword is a loud TypeError at the call site.
    """
    if not jd_text or not jd_text.strip():
        return {"skipped": True, "facts": {}}

    reply = await llm.complete(
        model=model,
        max_tokens=2048,
        temperature=0,
        system=PARSE_JD_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_parse_jd_user_prompt(jd_text)}],
    )

    # The model wraps its object in ```json — verified live. Without this the
    # JD parses to nothing and the intake silently loses everything the JD said.
    raw = strip_markdown_fence((reply.text or "").strip())
    if not raw:
        # An empty completion is this stage's degraded reply. Without this branch
        # it reaches json.loads(""), raises JSONDecodeError, and is logged as
        # "unparseable" with an empty `raw` — which reads as a model that
        # answered badly rather than one that did not answer at all. The two have
        # different fixes, so they get different log lines.
        logger.warning("jd_parse_empty_reply", alias=model)
        return {"skipped": False, "facts": {}}

    try:
        facts = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("jd_parse_unparseable", raw=raw[:500])
        facts = {}

    return {"skipped": False, "facts": facts}
