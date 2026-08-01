"""End-to-end smoke test for Phase 1: form → prefill → session ready.

Run after deploying intake-agent-context-builder Lambda and applying migrations.
Requires: TEST_USER_JWT, TEST_USER_ID, TEST_ORG_ID env vars.

Usage:
    python3 scripts/smoke_test_intake_v2.py
"""

from __future__ import annotations

import os
import time
import sys
import httpx


API_URL = os.environ.get("API_URL", "http://localhost:8000")
JWT = os.environ["TEST_USER_JWT"]


def main() -> int:
    headers = {"Authorization": f"Bearer {JWT}"}

    print("[1] Creating session...")
    create_resp = httpx.post(
        f"{API_URL}/v2/intake/sessions",
        json={
            "form_data": {
                "role_name": "Senior Backend Engineer (smoke test)",
                "experience_min": 5,
                "experience_max": 8,
                "location": "NYC",
                "jd_text": "Looking for a senior Python engineer with PostgreSQL and Kafka experience.",
            },
            "entry_point": "smoke_test",
        },
        headers=headers,
        timeout=10.0,
    )
    create_resp.raise_for_status()
    body = create_resp.json()
    session_id = body["session_id"]
    print(f"    session_id={session_id}")

    print("[2] Polling for status='ready' (Lambda runs ~10-15s)...")
    deadline = time.time() + 60
    while time.time() < deadline:
        get_resp = httpx.get(f"{API_URL}/v2/intake/sessions/{session_id}", headers=headers)
        get_resp.raise_for_status()
        s = get_resp.json()
        print(f"    status={s['status']} process_status={s.get('process_status')} stages={len(s.get('process_stages', []))}")
        if s["status"] == "ready":
            print("[3] Ready! Verifying prefilled_answers...")
            pa = s.get("prefilled_answers") or {}
            assert len(pa) == 9, f"Expected 9 prefilled answers, got {len(pa)}"
            print(f"    9 answers received. Sample Q4: {pa.get('q4_must_haves')}")
            return 0
        if s.get("process_status") == "failed":
            print(f"    FAILED: {s.get('process_error')}")
            return 1
        time.sleep(2)
    print("    TIMEOUT")
    return 1


if __name__ == "__main__":
    sys.exit(main())
