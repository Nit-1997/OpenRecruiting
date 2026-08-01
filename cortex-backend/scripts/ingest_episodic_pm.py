"""
Ingest episodic memory for AI Product Manager + Product Manager requisitions.
Sends question_summaries, interview_transcript, and feedback_debrief events
to the running cortex API, which fetches from Supabase internally.

Usage:
  python scripts/ingest_episodic_pm.py [--api-url http://localhost:8010]
"""
import argparse
from datetime import datetime, timezone

import httpx

ORG_ID = "70ba77bc-2939-419f-b569-d700fa1ff59c"

AI_PM_CR_IDS_WITH_SEGMENTS = [
    "26cd439a-8294-4ef4-a265-63b7a9584b1a",  # Nitin - Problem Solving
    "6affb0e5-b336-4962-8109-3ca3575eef1f",  # Prajwal Shenoy - Problem Solving
    "f9b702f7-a0a9-4d6a-afab-e4d5ff1f1ccb",  # Rishit Chaturvedi - Problem Solving
]

PM_CR_IDS_WITH_SEGMENTS = [
    "f90f65e7-3176-494a-b864-65669c4322df",  # Aaryaman
    "69db8a37-6836-4870-bbc1-6a8725f641d0",  # Ankit Dalal
    "21735b9e-ec90-412e-a2b1-3ac778e94603",  # anusha
    "2905ac19-b671-47e3-99a1-c5d298f03c48",  # boker
    "2b5130ce-9762-4ca5-bdb9-7965c9019d50",  # ClaudeO
    "5b21ea80-4a72-4287-b985-157cfeac2c1d",  # Cute
    "e6b99976-f1f8-43c5-ad15-220e9c0ade24",  # Feet are aching
    "f63ef2c8-8853-416e-9716-1495db7d432f",  # Gopal Bhakshi
    "ca7b461b-ea2c-4a71-af89-35811e4b410d",  # Gopal Joshi
    "df483da7-4156-4924-992c-c05f546ed748",  # Govind
    "af8d4472-811a-4771-8fe1-5cb63d18f79f",  # inrpogressstatusv2
    "02c9ebea-3069-4c40-8e90-35276163f53c",  # Naman Pranav
    "71d5179e-3cd9-4ce7-b8e8-a12f6f79ed04",  # Nikolia
    "0a8d2ec4-4ccb-499b-a07a-ccda0a93e14c",  # Nitin Bhat
    "433769e4-d1a1-4e98-a047-f5705663484a",  # Nitin Bhat
    "5f22bdc4-5219-4cc3-96bb-8e8800dff627",  # Nitin Bhat
    "18ad55cf-99a4-44e0-abce-9a3e4a1ec28c",  # Nitin Bhat
    "993e89bb-7a13-4625-9c31-c15b2f84e15f",  # Nitin Bhat
    "4779d2dc-ac17-427c-bf6d-593de5d7739d",  # Nitin Bhater
    "a713df78-f56f-40a6-9da3-d76fad8d7243",  # Nitin Bhati
    "8933f318-62d8-4810-b242-31eb8c6b7e95",  # no feedback
    "4c17d3ed-0def-429a-9b5f-4402d73999fe",  # Prajwal S
    "f1f97d13-9b29-4bfe-8a8a-a0330a5801a0",  # Prajwal Shenoy
    "4ccf93bd-c05a-4439-9856-0ac59c5275b8",  # Prajwal Shenoy
    "c144bb6a-9313-4671-a7bd-8fbc5f481fc3",  # Rakshit Soni
    "2c24456c-7127-4f21-8a00-e94955f8f763",  # riki
    "a27cef90-909f-400d-8dc6-158f71a4401c",  # Rishit Chaturvedi
    "946c313e-f56b-4ac2-9cba-4093ec39337d",  # Rishit Chaturvedi
    "e09e2ce8-fba0-4684-9334-fd4941333b35",  # Rishit Chaturvedi
    "4a68fe84-bad6-4182-b6ff-780c2c1dc305",  # Sushil
    "a03153a7-13b8-4958-9e40-fccabf266803",  # Test
    "f512f263-b101-40b8-b680-9bb963256964",  # Test1
    "80ccfc2d-4e06-4c55-967b-ad647078e9db",  # Testing_Feedback_IN_CALL_V2
    "0e361ade-125a-4c45-964f-8132fb75db5f",  # with feedback
    "924a65a8-58a6-4481-931e-364f89c48f97",  # wowletys
]

ALL_CR_IDS_WITH_SEGMENTS = AI_PM_CR_IDS_WITH_SEGMENTS + PM_CR_IDS_WITH_SEGMENTS

CR_IDS_WITH_QUESTION_SUMMARIES = [
    "f9b702f7-a0a9-4d6a-afab-e4d5ff1f1ccb",  # Rishit - AI PM
    "69db8a37-6836-4870-bbc1-6a8725f641d0",  # Ankit Dalal
    "21735b9e-ec90-412e-a2b1-3ac778e94603",  # anusha
    "2905ac19-b671-47e3-99a1-c5d298f03c48",  # boker
    "2b5130ce-9762-4ca5-bdb9-7965c9019d50",  # ClaudeO
    "e6b99976-f1f8-43c5-ad15-220e9c0ade24",  # Feet are aching
    "71d5179e-3cd9-4ce7-b8e8-a12f6f79ed04",  # Nikolia
    "0a8d2ec4-4ccb-499b-a07a-ccda0a93e14c",  # Nitin Bhat
    "433769e4-d1a1-4e98-a047-f5705663484a",  # Nitin Bhat
    "18ad55cf-99a4-44e0-abce-9a3e4a1ec28c",  # Nitin Bhat
    "993e89bb-7a13-4625-9c31-c15b2f84e15f",  # Nitin Bhat
    "4779d2dc-ac17-427c-bf6d-593de5d7739d",  # Nitin Bhater
    "4ccf93bd-c05a-4439-9856-0ac59c5275b8",  # Prajwal Shenoy
    "f1f97d13-9b29-4bfe-8a8a-a0330a5801a0",  # Prajwal Shenoy
    "c144bb6a-9313-4671-a7bd-8fbc5f481fc3",  # Rakshit Soni
    "2c24456c-7127-4f21-8a00-e94955f8f763",  # riki
    "946c313e-f56b-4ac2-9cba-4093ec39337d",  # Rishit Chaturvedi
    "a27cef90-909f-400d-8dc6-158f71a4401c",  # Rishit Chaturvedi
    "a03153a7-13b8-4958-9e40-fccabf266803",  # Test
    "0e361ade-125a-4c45-964f-8132fb75db5f",  # with feedback
    "02c9ebea-3069-4c40-8e90-35276163f53c",  # Naman Pranav
    "924a65a8-58a6-4481-931e-364f89c48f97",  # wowletys
    "80ccfc2d-4e06-4c55-967b-ad647078e9db",  # Testing_Feedback_IN_CALL_V2
]

CR_IDS_WITH_FEEDBACK_DEBRIEF = [
    "2905ac19-b671-47e3-99a1-c5d298f03c48",  # boker (2564 chars)
    "f63ef2c8-8853-416e-9716-1495db7d432f",  # Gopal Bhakshi (1092 chars)
    "df483da7-4156-4924-992c-c05f546ed748",  # Govind (331 chars)
    "71d5179e-3cd9-4ce7-b8e8-a12f6f79ed04",  # Nikolia (2524 chars)
    "0a8d2ec4-4ccb-499b-a07a-ccda0a93e14c",  # Nitin Bhat (1508 chars)
    "4779d2dc-ac17-427c-bf6d-593de5d7739d",  # Nitin Bhater (1610 chars)
    "2c24456c-7127-4f21-8a00-e94955f8f763",  # riki (2022 chars)
    "e09e2ce8-fba0-4684-9334-fd4941333b35",  # Rishit Chaturvedi (754 chars)
]


def send(client: httpx.Client, event_type: str, cr_id: str, headers: dict) -> dict:
    body = {
        "event_type": event_type,
        "org_id": ORG_ID,
        "source_ref": {"candidate_round_id": cr_id},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    resp = client.post("/api/v1/ingest", json=body, headers=headers)
    if resp.status_code != 200:
        return {"status": "error", "detail": resp.text, "nodes_created": 0, "edges_created": 0}
    return resp.json()


def run_batch(client: httpx.Client, headers: dict, event_type: str, label: str, cr_ids: list[str]):
    print(f"\n{'='*60}")
    print(f"  {label} ({len(cr_ids)} candidate_rounds)")
    print(f"  event_type: {event_type}")
    print(f"{'='*60}")

    total_nodes = 0
    total_edges = 0
    errors = 0
    skipped = 0

    for i, cr_id in enumerate(cr_ids):
        result = send(client, event_type, cr_id, headers)
        n = result.get("nodes_created", 0)
        e = result.get("edges_created", 0)
        status = result.get("status", "unknown")

        if status == "error":
            errors += 1
            print(f"  [{i+1:2d}/{len(cr_ids)}] {cr_id[:12]}... ERROR: {result.get('detail', '')[:80]}")
        elif n == 0 and e == 0:
            skipped += 1
            print(f"  [{i+1:2d}/{len(cr_ids)}] {cr_id[:12]}... skip (no data)")
        else:
            total_nodes += n
            total_edges += e
            print(f"  [{i+1:2d}/{len(cr_ids)}] {cr_id[:12]}... {n}n/{e}e")

    print(f"\n  Totals: {total_nodes} nodes, {total_edges} edges | {skipped} skipped | {errors} errors")
    return total_nodes, total_edges, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8010")
    parser.add_argument("--secret", default="test-secret-123")
    args = parser.parse_args()

    headers = {"X-Internal-Secret": args.secret}
    client = httpx.Client(base_url=args.api_url, timeout=120)

    print("=== Episodic Ingestion: AI PM + PM Requisitions ===")

    grand_n, grand_e, grand_err = 0, 0, 0

    n, e, err = run_batch(client, headers, "question_summaries_available", "Question Summaries", CR_IDS_WITH_QUESTION_SUMMARIES)
    grand_n += n; grand_e += e; grand_err += err

    n, e, err = run_batch(client, headers, "feedback_debrief_available", "Feedback Debriefs", CR_IDS_WITH_FEEDBACK_DEBRIEF)
    grand_n += n; grand_e += e; grand_err += err

    n, e, err = run_batch(client, headers, "interview_transcript_available", "Interview Transcripts", ALL_CR_IDS_WITH_SEGMENTS)
    grand_n += n; grand_e += e; grand_err += err

    print(f"\n{'='*60}")
    print(f"  GRAND TOTAL: {grand_n} nodes, {grand_e} edges, {grand_err} errors")
    print(f"{'='*60}")

    client.close()


if __name__ == "__main__":
    main()
