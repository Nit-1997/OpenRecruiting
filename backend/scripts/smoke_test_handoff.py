"""End-to-end smoke test for Phase 4: voice <-> text handoff.

Assumes Phases 1, 2, 3 are deployed locally:
  - backend on :8000
  - voice-agent on :8011
  - recruiter-app on :3004
A session has already been created and prefilled (use smoke_test_intake_v2.py
from Phase 1 to bootstrap one).

Required env:
  TEST_USER_JWT  - real JWT for the user owning the session
  SESSION_ID     - intake_sessions.id with status='ready'
  API_URL        - default http://localhost:8000

Test plan:
  1. Trigger voice path: POST /voice/start (Phase 2)        => active_modality=voice
  2. POST /switch?to=text                                    => drains voice, active_modality=text
  3. POST /voice/start while text holds the lock             => expect 409
  4. POST /switch?to=voice                                   => active_modality=voice, next_step=voice_start
"""

from __future__ import annotations

import os
import sys
import time

import httpx


API_URL = os.environ.get("API_URL", "http://localhost:8000")
JWT = os.environ["TEST_USER_JWT"]
SESSION_ID = os.environ["SESSION_ID"]
HEADERS = {"Authorization": f"Bearer {JWT}"}


def _print_session_modality(label: str) -> None:
    resp = httpx.get(f"{API_URL}/v2/intake/sessions/{SESSION_ID}", headers=HEADERS, timeout=10)
    resp.raise_for_status()
    am = resp.json().get("active_modality")
    print(f"    [{label}] active_modality={am}")


def main() -> int:
    print("[1] Starting voice session (Phase 2 endpoint)")
    r = httpx.post(f"{API_URL}/v2/intake/sessions/{SESSION_ID}/voice/start", headers=HEADERS, timeout=10)
    if r.status_code not in (200, 201):
        print(f"    SKIP: voice/start not available or returned unexpected status ({r.status_code}). Cannot test handoff.")
        return 2
    _print_session_modality("after voice/start")

    print("[2] Switching to text (drain voice)")
    t0 = time.monotonic()
    r = httpx.post(f"{API_URL}/v2/intake/sessions/{SESSION_ID}/switch?to=text", headers=HEADERS, timeout=15)
    elapsed = time.monotonic() - t0
    print(f"    status={r.status_code} elapsed={elapsed:.2f}s")
    if r.status_code != 200:
        print(f"    FAIL: switch to text returned {r.status_code}: {r.text[:300]}")
        return 1
    body = r.json()
    assert body["active_modality"] == "text", f"Expected active_modality=text, got {body.get('active_modality')}"
    assert body["drained"]["drained"] is True, "Expected drained.drained=true"
    _print_session_modality("after switch?to=text")

    print("[3] Trying voice/start while text holds the lock — expect 409")
    r = httpx.post(f"{API_URL}/v2/intake/sessions/{SESSION_ID}/voice/start", headers=HEADERS, timeout=10)
    if r.status_code != 409:
        print(f"    FAIL: expected 409 conflict, got {r.status_code}: {r.text[:300]}")
        return 1
    body = r.json()
    assert body.get("held") == "text", f"Expected held=text, got {body.get('held')}"
    print("    409 returned as expected")

    print("[4] Switching back to voice (no drain needed — text has no server-side worker)")
    r = httpx.post(f"{API_URL}/v2/intake/sessions/{SESSION_ID}/switch?to=voice", headers=HEADERS, timeout=10)
    if r.status_code != 200:
        print(f"    FAIL: switch to voice returned {r.status_code}: {r.text[:300]}")
        return 1
    body = r.json()
    assert body["active_modality"] == "voice", f"Expected active_modality=voice, got {body.get('active_modality')}"
    assert body["next_step"] == "voice_start", f"Expected next_step=voice_start, got {body.get('next_step')}"
    _print_session_modality("after switch?to=voice")

    print("[DONE] All handoff transitions succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
