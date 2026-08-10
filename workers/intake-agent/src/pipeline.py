"""Intake-agent v2 pipeline. Reads structured current_answers from intake_sessions
and runs rounds-design + parallel round-details Sonnet calls. Drops v1's brief/
classify/summarize stages — the structured answers ARE the summary.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from src.clients.llm import LLMGatewayClient
from src.clients.supabase import SupabaseClient
from src.logging import get_logger
from src.prompts import build_rounds_prompt, build_round_details_prompt

logger = get_logger(__name__)


def round_skeleton_to_artifact(
    round_id: str,
    skeleton: dict[str, Any],
    details: dict[str, Any],
    order_index: int,
) -> dict[str, Any]:
    """Map one round skeleton + its generated details into the editable
    interview_plan.rounds[] artifact (the UI source of truth). Pure function so the
    field carry-through (incl. the openrecruiting_screenable eligibility flag) is unit-testable.
    """
    return {
        "round_id": round_id,
        "name": skeleton["name"],
        "category": skeleton.get("category"),
        "description": skeleton.get("description"),
        "duration_minutes": skeleton.get("duration_minutes", 45),
        "skills": skeleton.get("skills", []),
        "openrecruiting_screenable": skeleton.get("openrecruiting_screenable", False),
        "openrecruiting_screenable_reason": skeleton.get("openrecruiting_screenable_reason", ""),
        "order_index": order_index,
        "guidelines": details.get("guidelines", []),
        "feedback_questions": details.get("feedback_questions", []),
    }


def format_current_answers_as_summary(
    current_answers: dict[str, Any],
    questions_snapshot: list[dict],
) -> str:
    """Deterministic summary builder. No LLM call. Replaces v1's Sonnet-summarize
    stage because current_answers is already structured.
    """
    if not questions_snapshot:
        # Fall back to natural key order if snapshot missing
        ordered = sorted(current_answers.keys())
        questions_snapshot = [{"id": qid, "topic": qid, "order": i} for i, qid in enumerate(ordered, 1)]

    lines: list[str] = []
    for q in sorted(questions_snapshot, key=lambda x: x.get("order", 0)):
        qid = q["id"]
        topic = q.get("topic", qid)
        ans = current_answers.get(qid) or {}
        text = (ans.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"## {topic}\n{text}\n")
    if not lines:
        return "(no answers recorded)"
    return "\n".join(lines)


class IntakePipelineV2:
    """Runs Stage 2a (rounds design) + Stage 2b (parallel round details)."""

    def __init__(self, llm: LLMGatewayClient, supabase: SupabaseClient, session_id: str):
        self.llm = llm
        self.supabase = supabase
        self.session_id = session_id

    async def run(self, role_context: dict[str, Any]) -> dict[str, Any]:
        pipeline_start = time.monotonic()

        summary = format_current_answers_as_summary(
            role_context.get("intake_summary_struct") or {},
            role_context.get("questions_snapshot") or [],
        )

        role_title = role_context.get("role_title", "Unknown")
        exp_min = role_context.get("experience_min_years", 0)
        exp_max = role_context.get("experience_max_years")
        experience_range = f"{exp_min}-{exp_max} years" if exp_max else f"{exp_min}+ years"

        # Header context the rounds prompt uses
        header = f"Role: {role_title}\nExperience: {experience_range}\n\n"
        full_summary = header + summary

        # Stage 2a: rounds skeletons
        stage_2a_start = time.monotonic()
        logger.info("stage_2a_rounds_start")
        rounds_prompt = build_rounds_prompt(intake_summary=full_summary)
        raw_rounds = await self.llm.call_sonnet(rounds_prompt, max_tokens=4096)
        round_skeletons = self._parse_rounds_json(raw_rounds)
        logger.info(
            "stage_2a_rounds_complete",
            round_count=len(round_skeletons),
            duration_ms=int((time.monotonic() - stage_2a_start) * 1000),
        )

        # Save skeletons → get back round IDs
        round_ids = await self.supabase.save_round_skeletons(
            role_context["requisition_id"], round_skeletons
        )

        # Stage 2b: parallel detail generation per round
        stage_2b_start = time.monotonic()

        async def detail_for(round_id: str, skeleton: dict) -> dict:
            prompt = build_round_details_prompt(
                round_skeleton=skeleton, intake_summary=full_summary
            )
            raw = await self.llm.call_sonnet(prompt, max_tokens=2048)
            details = self._parse_round_details_json(raw)
            await self.supabase.save_round_details(round_id, details)
            return details

        details_list = await asyncio.gather(
            *[detail_for(rid, s) for rid, s in zip(round_ids, round_skeletons)]
        )
        logger.info(
            "stage_2b_details_complete",
            detail_count=len(details_list),
            duration_ms=int((time.monotonic() - stage_2b_start) * 1000),
        )

        # Compose editable artifact (UI source of truth)
        interview_plan = {
            "version": "v1",
            "questions_version": role_context.get("questions_version"),
            "round_count": len(round_skeletons),
            "rounds": [
                round_skeleton_to_artifact(rid, skel, d, idx)
                for idx, (rid, skel, d) in enumerate(zip(round_ids, round_skeletons, details_list))
            ],
            "summary_used": summary,
        }

        await self.supabase.finalize_interview_plan(
            session_id=role_context["session_id"],
            requisition_id=role_context["requisition_id"],
            organization_id=role_context["organization_id"],
            interview_plan=interview_plan,
        )

        logger.info(
            "pipeline_complete",
            session_id=self.session_id,
            round_count=len(round_skeletons),
            total_duration_ms=int((time.monotonic() - pipeline_start) * 1000),
        )
        return interview_plan

    def _parse_rounds_json(self, raw: str) -> list[dict]:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict) or "rounds" not in parsed:
            raise ValueError("JSON must contain a 'rounds' key")
        rounds = parsed["rounds"]
        if not isinstance(rounds, list) or len(rounds) == 0:
            raise ValueError("'rounds' must be a non-empty array")
        for i, r in enumerate(rounds):
            if not r.get("name"):
                raise ValueError(f"Round {i+1} missing 'name'")
            if not r.get("category"):
                raise ValueError(f"Round {i+1} ({r['name']}) missing 'category'")
            if not r.get("skills"):
                raise ValueError(f"Round {i+1} ({r['name']}) missing 'skills'")
            if not isinstance(r.get("duration_minutes"), int) or r["duration_minutes"] < 1:
                r["duration_minutes"] = 45
        return rounds

    def _parse_round_details_json(self, raw: str) -> dict:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("Round details must be a JSON object")
        if not parsed.get("guidelines"):
            raise ValueError("Round details missing 'guidelines'")
        if not parsed.get("feedback_questions"):
            raise ValueError("Round details missing 'feedback_questions'")
        for q in parsed["feedback_questions"]:
            if not q.get("heading"):
                q["heading"] = "General Assessment"
        return parsed
