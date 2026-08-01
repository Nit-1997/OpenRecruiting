"""Side-by-side diff of two replay runs.

Usage:
    python -m scripts.diff_runs evals/runs/keerthi/run-A/ evals/runs/keerthi/run-B/
    python -m scripts.diff_runs evals/runs/keerthi/run-A/ evals/runs/keerthi/run-B/ --key summary
"""
from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path

STAGE_FILES = [
    "01_complete_result.json",
    "02_evidence_result.json",
    "03_judge_result.json",
    "04_summary_result.json",
    "manifest.json",
]


def _normalize(obj):
    """Sort lists of strings and lists of dicts (by str rep) for stable diffs."""
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        if all(isinstance(x, str) for x in obj):
            return sorted(obj)
        normalized = [_normalize(x) for x in obj]
        try:
            return sorted(normalized, key=lambda x: json.dumps(x, sort_keys=True))
        except TypeError:
            return normalized
    return obj


def _load_stage(run_dir: Path, filename: str):
    path = run_dir / filename
    if not path.exists():
        return None
    return _normalize(json.loads(path.read_text()))


def diff_runs(run_a: Path, run_b: Path, key: str | None = None) -> None:
    files = STAGE_FILES
    if key:
        matches = [f for f in STAGE_FILES if key.lower() in f.lower()]
        if not matches:
            raise SystemExit(f"--key {key!r} matched no stage file. Choices: {STAGE_FILES}")
        files = matches

    for filename in files:
        a = _load_stage(run_a, filename)
        b = _load_stage(run_b, filename)
        if a is None and b is None:
            continue
        a_text = json.dumps(a, indent=2, default=str).splitlines()
        b_text = json.dumps(b, indent=2, default=str).splitlines()
        diff = list(difflib.unified_diff(
            a_text, b_text,
            fromfile=f"A/{filename}",
            tofile=f"B/{filename}",
            n=3,
        ))
        if diff:
            print("\n".join(diff))
            print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_a", type=Path)
    ap.add_argument("run_b", type=Path)
    ap.add_argument("--key", default=None,
                    help="Substring to filter stage files (e.g. 'summary')")
    args = ap.parse_args()
    diff_runs(args.run_a, args.run_b, args.key)


if __name__ == "__main__":
    main()
