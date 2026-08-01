"""Run the feedback pipeline locally against a Fixture JSON file.

Dumps each stage's output to evals/runs/{round_id}/{timestamp}/ for diffing
and manual review. Makes real LLM calls; do not run in CI unless you've
budgeted for the spend (~$0.30-0.80 per fixture).

Usage:
    python -m scripts.replay evals/fixtures/keerthi_fbdcfddc.json
    python -m scripts.replay evals/fixtures/keerthi_fbdcfddc.json --output-dir custom/path
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import subprocess
import time
from pathlib import Path

from scripts._fixture_schema import Fixture
from src.config import get_settings
from src.jobs.processor import JobProcessor
from src.logging import configure_logging, get_logger
from src.runner import run_pipeline_for_inputs

settings = get_settings()
configure_logging(level=settings.log_level, format=settings.log_format)
logger = get_logger(__name__)


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        return "unknown"


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


async def replay(fixture_path: Path, output_dir: Path) -> Path:
    fixture = Fixture.model_validate_json(fixture_path.read_text())

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir = output_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "replay_start",
        fixture=str(fixture_path),
        round_id=fixture.round_id,
        source=fixture.feedback_source.source,
        run_dir=str(run_dir),
    )

    processor = JobProcessor(supabase=None)
    start = time.monotonic()

    result = await run_pipeline_for_inputs(
        feedback_source=fixture.feedback_source.model_dump(),
        questions=[q.model_dump() for q in fixture.questions],
        role_context=fixture.role_context.model_dump(),
        transcript=fixture.transcript.model_dump(),
        processor=processor,
    )

    duration_s = time.monotonic() - start

    # Dump intermediates.
    stage_filenames = {
        "complete_result": "01_complete_result.json",
        "evidence_result": "02_evidence_result.json",
        "judge_result": "03_judge_result.json",
        "summary_result": "04_summary_result.json",
    }
    for key, filename in stage_filenames.items():
        (run_dir / filename).write_text(
            json.dumps(result.get(key, {}), indent=2, default=str)
        )

    manifest = {
        "fixture_path": str(fixture_path),
        "fixture_sha256": _file_sha(fixture_path),
        "round_id": fixture.round_id,
        "git_sha": _git_sha(),
        "model_sonnet": settings.anthropic_model_sonnet,
        "model_haiku": settings.anthropic_model_haiku,
        "timestamp": timestamp,
        "duration_seconds": round(duration_s, 1),
        "baseline_outputs": fixture.baseline_outputs.model_dump(),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    logger.info(
        "replay_complete",
        run_dir=str(run_dir),
        duration_seconds=round(duration_s, 1),
    )

    return run_dir


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture", type=Path)
    ap.add_argument("--output-dir", type=Path, default=None)
    args = ap.parse_args()

    if args.output_dir is None:
        fixture_stem = args.fixture.stem  # e.g., "keerthi_fbdcfddc"
        args.output_dir = Path("evals/runs") / fixture_stem

    run_dir = asyncio.run(replay(args.fixture, args.output_dir))
    print(f"wrote {run_dir}")


if __name__ == "__main__":
    main()
