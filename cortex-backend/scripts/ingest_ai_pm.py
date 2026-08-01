"""
Ingest two AI Product Manager requisitions end-to-end.
  - Req 1: AI Product Manager - Bangalore (13c9ecf3)
  - Req 2: AI Product Manager - San Mateo  (fd6c0c87)
Sends plan_created + feedback_completed events (no decisions).

Usage:
  python scripts/ingest_ai_pm.py [--api-url http://localhost:8010] [--secret <secret>]
"""
import argparse
from datetime import datetime, timezone

import httpx

ORG_ID = "70ba77bc-2939-419f-b569-d700fa1ff59c"

REQ1_ID = "13c9ecf3-b1c5-474f-9d12-cc5a333a7a87"
REQ2_ID = "fd6c0c87-0acc-4106-a48a-609f88f47280"

REQ1 = {
    "id": REQ1_ID,
    "role_title": "AI Product Manager",
    "organization_id": ORG_ID,
    "status": "planned",
    "experience_min_years": 0,
    "experience_max_years": 8,
    "role_location": "Bangalore",
    "must_have_skills": [],
    "nice_to_have_skills": [],
}

REQ2 = {
    "id": REQ2_ID,
    "role_title": "AI Product Manager",
    "organization_id": ORG_ID,
    "status": "planned",
    "experience_min_years": 0,
    "experience_max_years": 12,
    "role_location": "San Mateo, CA",
    "must_have_skills": [],
    "nice_to_have_skills": [],
}

ROUNDS_REQ1 = [
    {
        "id": "b5b32ce8-0016-4fed-a729-991d0da892e3",
        "name": "AI PM",
        "category": "assessment",
        "duration_minutes": 45,
        "skills": [],
        "competency_headings": ["Code Quality", "Communication", "Edge Case Handling", "Problem Decomposition"],
        "order": 1,
    },
    {
        "id": "8af6c28c-0743-4c78-a2b0-e9bb87a43bf2",
        "name": "Problem Solving",
        "category": "coding",
        "duration_minutes": 45,
        "skills": ["Data Structures", "Algorithms", "Problem Decomposition", "Code Quality"],
        "competency_headings": ["Adaptability", "Code Quality", "Communication", "Edge Case Handling", "Object Oriented Design", "Problem Decomposition", "Requirements Clarification", "Working Demo"],
        "order": 2,
    },
    {
        "id": "00abb31e-b835-4c97-8da8-8ced1f542ced",
        "name": "Machine Coding",
        "category": "coding",
        "duration_minutes": 60,
        "skills": ["OOPS", "Design Patterns", "Clean Code", "Unit Testing"],
        "competency_headings": ["Adaptability", "Architecture Quality", "Object Oriented Design", "Requirements Analysis", "Requirements Clarification", "Scalability", "Trade-off Analysis", "Working Demo"],
        "order": 3,
    },
    {
        "id": "09f94715-74d6-4c25-b4a8-0e6d939ecda7",
        "name": "Systems Design",
        "category": "design",
        "duration_minutes": 45,
        "skills": ["Distributed Systems", "Scalability", "Database Design", "Caching", "Load Balancing"],
        "competency_headings": ["Architecture Quality", "Communication", "Conflict Resolution", "Leadership", "Ownership", "Requirements Analysis", "Scalability", "Trade-off Analysis"],
        "order": 4,
    },
    {
        "id": "6d804185-a8c9-4fe2-8e05-481a96aa0383",
        "name": "Behavioural",
        "category": "behavioural",
        "duration_minutes": 30,
        "skills": ["Leadership", "Communication", "Teamwork", "Conflict Resolution", "Ownership"],
        "competency_headings": ["Communication", "Conflict Resolution", "Leadership", "Ownership"],
        "order": 5,
    },
    {
        "id": "e4bbfad9-ca3c-4303-b0bc-6025703f66ff",
        "name": "AI PM",
        "category": "assessment",
        "duration_minutes": 45,
        "skills": [],
        "competency_headings": [],
        "order": 6,
    },
]

ROUNDS_REQ2 = [
    {
        "id": "081ba1da-c803-4015-85e6-0a746fff9c74",
        "name": "Problem Solving",
        "category": "coding",
        "duration_minutes": 45,
        "skills": ["Data Structures", "Algorithms", "Problem Decomposition", "Code Quality"],
        "competency_headings": ["Code Quality", "Communication", "Edge Case Handling", "Problem Decomposition"],
        "order": 1,
    },
    {
        "id": "8c2d9c27-79a6-4ea6-8b54-7941ca663633",
        "name": "Machine Coding",
        "category": "coding",
        "duration_minutes": 60,
        "skills": ["OOPS", "Design Patterns", "Clean Code", "Unit Testing"],
        "competency_headings": ["Adaptability", "Object Oriented Design", "Requirements Clarification", "Working Demo"],
        "order": 2,
    },
    {
        "id": "6186c9bc-945a-4b5f-b5a8-b08d226aca67",
        "name": "Systems Design",
        "category": "design",
        "duration_minutes": 45,
        "skills": ["Distributed Systems", "Scalability", "Database Design", "Caching", "Load Balancing"],
        "competency_headings": ["Architecture Quality", "Requirements Analysis", "Scalability", "Trade-off Analysis"],
        "order": 3,
    },
    {
        "id": "2ba9ce88-e366-4800-bdd3-ebed828e2ec3",
        "name": "Systems Design",
        "category": "design",
        "duration_minutes": 45,
        "skills": ["Distributed Systems", "Scalability", "Database Design", "Caching", "Load Balancing"],
        "competency_headings": ["Architecture Quality", "Requirements Analysis", "Scalability", "Trade-off Analysis"],
        "order": 4,
    },
    {
        "id": "3cf28c94-7794-48c6-828d-71d787ba4cac",
        "name": "Behavioural",
        "category": "behavioural",
        "duration_minutes": 30,
        "skills": ["Leadership", "Communication", "Teamwork", "Conflict Resolution", "Ownership"],
        "competency_headings": ["Communication", "Conflict Resolution", "Leadership", "Ownership"],
        "order": 5,
    },
]

ROUND_LOOKUP_REQ1 = {r["id"]: r for r in ROUNDS_REQ1}
ROUND_LOOKUP_REQ2 = {r["id"]: r for r in ROUNDS_REQ2}

CANDIDATES_REQ1 = {
    "cd22963a-c612-4ea0-b804-bebe8a68ac6f": {"name": "Rishit Chaturvedi", "status": "active"},
}

CANDIDATES_REQ2 = {
    "1979e22c-1180-4711-aefa-5e50b9fc25f5": {"name": "Nitin", "status": "active"},
    "063f643f-efc1-4207-b00d-581a2884aa57": {"name": "Prajwal Shenoy", "status": "active"},
    "1c4b480c-63a1-4778-8f5f-2b6a3ef6b322": {"name": "Ramesh", "status": "active"},
}

INTERVIEWS_REQ1 = [
    {
        "cr_id": "8af6c28c-0743-4c78-a2b0-e9bb87a43bf2",
        "cand_id": "cd22963a-c612-4ea0-b804-bebe8a68ac6f",
        "round_id": "8af6c28c-0743-4c78-a2b0-e9bb87a43bf2",
        "rating": "maybe",
        "interviewer_email": "bhat.nit@northeastern.edu",
        "headings": ["Adaptability", "Code Quality", "Communication", "Edge Case Handling", "Object Oriented Design", "Problem Decomposition", "Requirements Clarification", "Working Demo"],
    },
]

INTERVIEWS_REQ2 = [
    {
        "cr_id": "081ba1da-c803-4015-85e6-0a746fff9c74-nitin",
        "cand_id": "1979e22c-1180-4711-aefa-5e50b9fc25f5",
        "round_id": "081ba1da-c803-4015-85e6-0a746fff9c74",
        "rating": "maybe",
        "interviewer_email": None,
        "headings": ["Code Quality", "Communication", "Edge Case Handling", "Problem Decomposition"],
    },
    {
        "cr_id": "081ba1da-c803-4015-85e6-0a746fff9c74-prajwal",
        "cand_id": "063f643f-efc1-4207-b00d-581a2884aa57",
        "round_id": "081ba1da-c803-4015-85e6-0a746fff9c74",
        "rating": "maybe",
        "interviewer_email": None,
        "headings": ["Code Quality", "Communication", "Edge Case Handling", "Problem Decomposition"],
    },
]


def send(client: httpx.Client, event_type: str, org_id: str, payload: dict, headers: dict) -> dict:
    body = {
        "event_type": event_type,
        "org_id": org_id,
        "source_ref": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    resp = client.post("/api/v1/ingest/direct", json=body, headers=headers)
    return resp.json()


def ingest_requisition(client: httpx.Client, headers: dict, req: dict, rounds: list, round_lookup: dict, candidates: dict, interviews: list) -> tuple[int, int, list]:
    total_nodes = 0
    total_edges = 0
    errors = []
    req_id = req["id"]

    print(f"\n--- Requisition: {req['role_title']} - {req['role_location']} ({req_id}) ---\n")

    print("1. plan_created...")
    plan_payload = {"requisition": req, "rounds": rounds}
    result = send(client, "plan_created", ORG_ID, plan_payload, headers)
    print(f"   {result['status']}: {result['nodes_created']} nodes, {result['edges_created']} edges")
    total_nodes += result["nodes_created"]
    total_edges += result["edges_created"]
    if result.get("errors"):
        errors.extend(result["errors"])

    if not interviews:
        print("\n2. No feedback events to send.")
        return total_nodes, total_edges, errors

    print(f"\n2. feedback_completed x {len(interviews)}...")
    for i, iv in enumerate(interviews):
        cand = candidates[iv["cand_id"]]
        rd = round_lookup[iv["round_id"]]
        feedback_items = [{"heading": h, "question_id": None} for h in iv.get("headings", [])]

        payload = {
            "candidate_round": {
                "id": iv["cr_id"],
                "candidate_id": iv["cand_id"],
                "round_id": iv["round_id"],
                "requisition_id": req_id,
                "rating": iv["rating"],
                "interviewer_email": iv["interviewer_email"],
                "organization_id": ORG_ID,
            },
            "round": {
                "id": rd["id"],
                "name": rd["name"],
                "requisition_id": req_id,
                "category": rd["category"],
                "duration_minutes": rd["duration_minutes"],
                "skills": rd["skills"],
            },
            "requisition": req,
            "candidate": {
                "id": iv["cand_id"],
                "name": cand["name"],
                "organization_id": ORG_ID,
                "status": cand["status"],
            },
            "feedback_items": feedback_items,
        }
        result = send(client, "feedback_completed", ORG_ID, payload, headers)
        marker = "." if result["status"] == "ingested" else "!"
        print(f"   [{i+1:2d}/{len(interviews)}] {cand['name'][:20]:<20s} {iv['rating']:<12s} -> {result['status']} ({result['nodes_created']}n/{result['edges_created']}e){marker}")
        total_nodes += result["nodes_created"]
        total_edges += result["edges_created"]
        if result.get("errors"):
            errors.extend(result["errors"])

    return total_nodes, total_edges, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8010")
    parser.add_argument("--secret", default="test-secret-123")
    args = parser.parse_args()

    headers = {"X-Internal-Secret": args.secret}
    client = httpx.Client(base_url=args.api_url, timeout=300)

    total_nodes = 0
    total_edges = 0
    errors = []

    print("=== Ingesting AI Product Manager requisitions ===")

    n, e, errs = ingest_requisition(client, headers, REQ1, ROUNDS_REQ1, ROUND_LOOKUP_REQ1, CANDIDATES_REQ1, INTERVIEWS_REQ1)
    total_nodes += n
    total_edges += e
    errors.extend(errs)

    n, e, errs = ingest_requisition(client, headers, REQ2, ROUNDS_REQ2, ROUND_LOOKUP_REQ2, CANDIDATES_REQ2, INTERVIEWS_REQ2)
    total_nodes += n
    total_edges += e
    errors.extend(errs)

    print(f"\n{'='*50}")
    print(f"TOTAL: {total_nodes} nodes, {total_edges} edges")
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors[:10]:
            print(f"  - {e}")
    else:
        print("No errors.")

    client.close()


if __name__ == "__main__":
    main()
