"""End-to-end smoke test for Phase 5: submit -> Lambda -> publish -> Cortex.

Pre-requisite: a session ID already in status='ready' (use Phase 1 smoke test
to create one, OR pick one from your dogfood org).

Usage:
    export TEST_USER_JWT="<paste JWT>"
    export TEST_SESSION_ID="<session uuid in status=ready>"
    export API_URL="http://localhost:8000"
    python3 scripts/smoke_test_intake_v2_submit.py
"""
from __future__ import annotations

import os
import sys
import time

import httpx


def main() -> int:
    api_url = os.environ.get("API_URL", "http://localhost:8000")
    jwt = os.environ["TEST_USER_JWT"]
    session_id = os.environ["TEST_SESSION_ID"]
    headers = {"Authorization": f"Bearer {jwt}"}

    print(f"[1] Submitting session {session_id}...")
    r = httpx.post(f"{api_url}/api/v2/intake/sessions/{session_id}/submit", headers=headers, timeout=10.0)
    r.raise_for_status()
    body = r.json()
    assert body["status"] == "submitted", body
    print(f"    status={body['status']}")

    print("[2] Polling for interview_plan...")
    deadline = time.time() + 120
    plan = None
    while time.time() < deadline:
        r = httpx.get(f"{api_url}/api/v2/intake/sessions/{session_id}", headers=headers)
        r.raise_for_status()
        s = r.json()
        print(f"    status={s['status']} process_status={s.get('process_status')}")
        if s.get("interview_plan"):
            plan = s["interview_plan"]
            assert plan.get("round_count", 0) > 0, f"interview_plan has no rounds: {plan}"
            print(f"    plan ready: {plan['round_count']} rounds")
            break
        if s.get("process_status") == "failed":
            print(f"    FAILED: {s.get('process_error')}")
            return 1
        time.sleep(3)
    if not plan:
        print("    TIMEOUT waiting for interview_plan")
        return 1

    print("[3] Publishing (no edits)...")
    r = httpx.post(
        f"{api_url}/api/v2/intake/sessions/{session_id}/publish",
        json={"interview_plan": None},
        headers=headers,
        timeout=30.0,
    )
    r.raise_for_status()
    body = r.json()
    requisition_id = body["requisition_id"]
    print(f"    requisition_id={requisition_id} redirect={body['redirect_url']}")

    print("[4] Verifying session.status=published...")
    r = httpx.get(f"{api_url}/api/v2/intake/sessions/{session_id}", headers=headers)
    r.raise_for_status()
    assert r.json()["status"] == "published", r.json()

    print("[5] Verify Cortex ingestion in CloudWatch / log stream for cortex-backend:")
    print("    grep 'intake_v2_triplets_built' — must contain this session_id")
    print("    grep 'intake_v2_episode_added' — must contain this session_id (if turns >= 3)")

    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
