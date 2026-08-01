"""get_cortex_context — return the static schema + tenancy rule + examples doc.

The Markdown file is read once at import time and cached for the process
lifetime. It's identical for every customer; tenant context comes from the
JWT, not from this doc.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path


_DOC_PATH = Path(__file__).resolve().parent.parent / "docs" / "cortex_context.md"


@lru_cache(maxsize=1)
def _doc_text() -> str:
    return _DOC_PATH.read_text(encoding="utf-8")


async def get_cortex_context() -> str:
    return _doc_text()
