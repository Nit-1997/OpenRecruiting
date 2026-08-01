"""Stage 2: parse JD into structured facts via Sonnet."""

from __future__ import annotations

import json
from typing import Any, Optional

import structlog
from anthropic import AsyncAnthropic

from ..prompts.parse_jd import PARSE_JD_SYSTEM_PROMPT, build_parse_jd_user_prompt

logger = structlog.get_logger(__name__)


async def parse_jd(
    anthropic_client: AsyncAnthropic,
    model: str,
    jd_text: Optional[str],
) -> dict[str, Any]:
    if not jd_text or not jd_text.strip():
        return {"skipped": True, "facts": {}}

    response = await anthropic_client.messages.create(
        model=model,
        max_tokens=2048,
        temperature=0,
        system=PARSE_JD_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_parse_jd_user_prompt(jd_text)}],
    )

    raw = response.content[0].text.strip()
    try:
        facts = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("jd_parse_unparseable", raw=raw[:500])
        facts = {}

    return {"skipped": False, "facts": facts}
