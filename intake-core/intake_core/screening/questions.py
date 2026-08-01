"""Screening question model + per-session snapshot helper.

Unlike the fixed 9-question intake set, screening questions are configured per
role and live in the DB. `snapshot_questions` deep-copies the DB rows into an
ordered, JSON-serializable snapshot pinned to a session.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class ScreeningQuestion:
    id: str
    order_index: int
    title: str
    prompt: str
    probe: str = ""
    signal: str = ""
    dimension: str = ""
    duration_minutes: int = 5


def snapshot_questions(rows: list[dict]) -> list[dict]:
    """Deep-copy DB question rows into an ordered snapshot for a session."""
    out = []
    for i, r in enumerate(sorted(rows, key=lambda x: x.get("order_index", 0))):
        out.append(asdict(ScreeningQuestion(
            id=str(r["id"]), order_index=i, title=r.get("title", ""),
            prompt=r["prompt"], probe=r.get("probe", "") or "",
            signal=r.get("signal", "") or "", dimension=r.get("dimension", "") or "",
            duration_minutes=r.get("duration_minutes") or 5)))
    return out
