"""Export v2 request schemas as JSON Schema for FE contract tests.

Runs at the start of `bun test` on the FE (via package.json prebuild hook)
OR manually before contract tests: `python3 scripts/export_v2_schemas.py`.

Output: recruiter-app/src/test/contract/v2-schemas.generated.json

The FE contract tests load this file and assert that the FE's
ScheduleInterviewInput / SubmitFeedbackRequest types match the BE's
required/optional/enum surface. If a BE schema gains a required field,
the matching FE contract test fails — that's the drift alarm we wanted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Resolve repo paths from this script's location so it works from any cwd.
THIS = Path(__file__).resolve()
BACKEND_ROOT = THIS.parent.parent  # backend
REPO_ROOT = BACKEND_ROOT.parent  # OpenRecruiting
OUTPUT = REPO_ROOT / "recruiter-app" / "src" / "test" / "contract" / "v2-schemas.generated.json"

# Make the backend's `app` package importable when this script runs from
# its own directory.
sys.path.insert(0, str(BACKEND_ROOT))

from app.api.v2.schemas.feedback import (  # noqa: E402
    ReprocessRequest,
    RequestFeedbackRequest,
    SubmitFeedbackRequest,
)
from app.api.v2.schemas.interview import (  # noqa: E402
    RescheduleInterviewRequest,
    ScheduleInterviewRequest,
)
from app.api.v2.schemas.round import (  # noqa: E402
    AddQuestionRequest,
    AddRoundRequest,
    ReorderRoundItem,
    UpdateQuestionRequest,
    UpdateRoundRequest,
)


SCHEMAS = {
    # Journey
    "ScheduleInterviewRequest": ScheduleInterviewRequest,
    "RescheduleInterviewRequest": RescheduleInterviewRequest,
    # Feedback
    "SubmitFeedbackRequest": SubmitFeedbackRequest,
    "RequestFeedbackRequest": RequestFeedbackRequest,
    "ReprocessRequest": ReprocessRequest,
    # Plan
    "AddRoundRequest": AddRoundRequest,
    "UpdateRoundRequest": UpdateRoundRequest,
    "ReorderRoundItem": ReorderRoundItem,
    "AddQuestionRequest": AddQuestionRequest,
    "UpdateQuestionRequest": UpdateQuestionRequest,
}


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        name: model.model_json_schema()
        for name, model in SCHEMAS.items()
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(f"Wrote {len(payload)} schemas → {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
