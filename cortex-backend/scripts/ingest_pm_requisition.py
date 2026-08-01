"""
Ingest the full Product Manager requisition (4a605206) end-to-end.
Sends plan_created + 35 feedback_completed + 5 decision_made events.

Usage:
  python scripts/ingest_pm_requisition.py [--api-url http://localhost:8010] [--secret <secret>]
"""
import argparse
import json
import sys
from datetime import datetime, timezone

import httpx

ORG_ID = "70ba77bc-2939-419f-b569-d700fa1ff59c"
REQ_ID = "4a605206-851b-44ad-bc99-5d9cd7bc91cb"

REQUISITION = {
    "id": REQ_ID,
    "role_title": "Product Manager",
    "organization_id": ORG_ID,
    "status": "planned",
    "experience_min_years": 0,
    "experience_max_years": 3,
    "role_location": "Bangalore, India",
    "must_have_skills": [],
    "nice_to_have_skills": [],
}

ROUNDS = [
    {
        "id": "06f0f715-5707-4f08-b07a-382e3f3215e4",
        "name": "Product Sense",
        "category": "coding",
        "duration_minutes": 45,
        "skills": [],
        "competency_headings": ["Problem Decomposition", "Product Sense", "User Empathy", "Code Quality", "Pricing", "Edge Case Handling"],
        "order": 1,
    },
    {
        "id": "c83ae9e9-4fce-4f65-ad50-e42a6b5ab649",
        "name": "Machine Coding",
        "category": "coding",
        "duration_minutes": 60,
        "skills": ["OOPS", "Design Patterns", "Clean Code", "Unit Testing"],
        "competency_headings": ["Requirements Clarification", "Object Oriented Design", "Adaptability", "Working Demo"],
        "order": 2,
    },
    {
        "id": "0be49fcc-186d-4ac9-9e85-09a2faea425d",
        "name": "New Round",
        "category": "coding",
        "duration_minutes": 45,
        "skills": ["Technical Skills"],
        "competency_headings": ["Rate candidate's technical skills"],
        "order": 2,
    },
    {
        "id": "6ac3d006-73c5-4499-91e8-20cf2430ad48",
        "name": "Systems Design",
        "category": "design",
        "duration_minutes": 45,
        "skills": ["Distributed Systems", "Scalability", "Database Design", "Caching", "Load Balancing"],
        "competency_headings": ["Requirements Analysis", "Architecture Quality", "Trade-off Analysis", "Scalability"],
        "order": 3,
    },
    {
        "id": "8b6f6625-fbbf-448b-ae09-1a27fa6752df",
        "name": "Behavioural",
        "category": "behavioural",
        "duration_minutes": 30,
        "skills": ["Leadership", "Communication", "Teamwork", "Conflict Resolution", "Ownership"],
        "competency_headings": ["Leadership", "Conflict Resolution", "Ownership", "Communication"],
        "order": 4,
    },
]

CANDIDATES = {
    "05ee1ff0-8f24-434c-9c22-416f2ed6c93a": {"name": "Ankit Dalal", "status": "hired"},
    "1049452d-8044-4cce-8b9d-d99d36b011e7": {"name": "Rishit Chaturvedi", "status": "hired"},
    "c35114f0-c0da-42ad-8e0e-19dfd8bacf1c": {"name": "Feet are aching", "status": "hired"},
    "85528ddc-7c77-4c1a-8334-487deecc9700": {"name": "Naman Pranav", "status": "hired"},
    "abc82de6-8470-49ef-ab2c-0c3c545bad08": {"name": "Rishit Chaturvedi", "status": "rejected"},
    "12a00086-bc56-4f87-ba63-ae1187ede89b": {"name": "Test", "status": "active"},
    "1895739e-3a4c-4cc4-921d-a393352ca321": {"name": "boker", "status": "active"},
    "1eb770bf-499b-423b-bfe2-e5cc0631fb63": {"name": "Nitin Bhat", "status": "active"},
    "31323bac-0336-4a52-b3ec-a0cff500345c": {"name": "Rishit Chaturvedi", "status": "active"},
    "35716fc6-ada4-4e59-9871-faed7b574fd1": {"name": "asdasd", "status": "active"},
    "44122c65-c32a-4ec4-9a4e-c328bdbc4557": {"name": "Nikolia", "status": "active"},
    "498b9d12-ab9b-4f32-bb38-66c7a66c30b0": {"name": "Test1", "status": "active"},
    "49ef1930-cc44-4fcb-ad2b-3b8bb0641d33": {"name": "Prajwal Shenoy", "status": "active"},
    "4f5b89c6-d0ff-455d-b338-02a0f1a5b8b4": {"name": "Prajwal Shenoy", "status": "active"},
    "523d4a45-4808-40b1-8d60-9df67def2658": {"name": "Nitin Bhat", "status": "active"},
    "56fbc23e-9c13-4c9b-9137-a4efccf9ddd5": {"name": "Nitin Bhater", "status": "active"},
    "5f74253e-2f96-4578-8473-9580d481b2bb": {"name": "wowletys", "status": "active"},
    "648e594d-be1a-47eb-ba1d-db737d54d0f1": {"name": "with feedback", "status": "active"},
    "79219792-bf26-4123-97e2-21a6eafbaf9f": {"name": "riki", "status": "active"},
    "875fb534-d913-4930-bfa9-ec5a33502272": {"name": "no feedback", "status": "active"},
    "9963291e-9874-48b7-b1e9-ab3e95d6be03": {"name": "Nitin Bhat", "status": "active"},
    "a2b155dd-bb49-43e6-9fd2-53fad77f4437": {"name": "Sushil", "status": "active"},
    "a539d7dd-28c6-4153-9656-d10f7216dc6f": {"name": "Cute", "status": "active"},
    "c12f2276-624b-43df-ada0-cec4d56a55a3": {"name": "Prajwal S", "status": "active"},
    "c1423b50-92e4-4a9f-a129-71733a643698": {"name": "ClaudeO", "status": "active"},
    "c2d7238d-1a07-413c-a541-40c92eded8b0": {"name": "Gopal Bhakshi", "status": "active"},
    "c9b95ec3-1266-4edf-a004-106f5bfaa8e6": {"name": "anusha", "status": "active"},
    "c9c08d24-80db-4cad-a26c-8c7637ca23a9": {"name": "Rakshit Soni", "status": "active"},
    "d61f51ce-cc69-41e9-9bff-3795a9deb2f2": {"name": "Nitin Bhat", "status": "active"},
    "d987b91f-4639-42a7-8418-3e982fc3a318": {"name": "Govind", "status": "active"},
    "e49e49bf-b970-4913-94c5-01d2ef15a2f3": {"name": "Nitin Bhat", "status": "active"},
    "eb0bd449-3a35-4960-9778-599bac0b560d": {"name": "inrpogressstatusv2", "status": "active"},
    "f03f3f4b-9d7f-4df5-a2bd-7e5804d388fd": {"name": "Gopal Joshi", "status": "active"},
    "f24b68c6-26cd-4085-9673-a36702c72756": {"name": "Nitin Bhati", "status": "active"},
    "f47bb150-a61c-4f70-aab2-6e1cf9011626": {"name": "Testing_Feedback_IN_CALL_V2", "status": "active"},
}

ROUND_LOOKUP = {r["id"]: r for r in ROUNDS}

INTERVIEWS = [
    {"cr_id": "69db8a37-6836-4870-bbc1-6a8725f641d0", "cand_id": "05ee1ff0-8f24-434c-9c22-416f2ed6c93a", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_yes", "interviewer_email": None},
    {"cr_id": "946c313e-f56b-4ac2-9cba-4093ec39337d", "cand_id": "1049452d-8044-4cce-8b9d-d99d36b011e7", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_yes", "interviewer_email": None},
    {"cr_id": "a03153a7-13b8-4958-9e40-fccabf266803", "cand_id": "12a00086-bc56-4f87-ba63-ae1187ede89b", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "yes", "interviewer_email": "anushachaturvedi18@gmail.com"},
    {"cr_id": "2905ac19-b671-47e3-99a1-c5d298f03c48", "cand_id": "1895739e-3a4c-4cc4-921d-a393352ca321", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "maybe", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "433769e4-d1a1-4e98-a047-f5705663484a", "cand_id": "1eb770bf-499b-423b-bfe2-e5cc0631fb63", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "yes", "interviewer_email": None},
    {"cr_id": "e09e2ce8-fba0-4684-9334-fd4941333b35", "cand_id": "31323bac-0336-4a52-b3ec-a0cff500345c", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_no", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "64d96196-4673-4b6f-a097-785b4bd0c4b1", "cand_id": "35716fc6-ada4-4e59-9871-faed7b574fd1", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_yes", "interviewer_email": "anushachaturvedi18@gmail.com"},
    {"cr_id": "71d5179e-3cd9-4ce7-b8e8-a12f6f79ed04", "cand_id": "44122c65-c32a-4ec4-9a4e-c328bdbc4557", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "maybe", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "f512f263-b101-40b8-b680-9bb963256964", "cand_id": "498b9d12-ab9b-4f32-bb38-66c7a66c30b0", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "maybe", "interviewer_email": "anushachaturvedi18@gmail.com"},
    {"cr_id": "f1f97d13-9b29-4bfe-8a8a-a0330a5801a0", "cand_id": "49ef1930-cc44-4fcb-ad2b-3b8bb0641d33", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_no", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "4ccf93bd-c05a-4439-9856-0ac59c5275b8", "cand_id": "4f5b89c6-d0ff-455d-b338-02a0f1a5b8b4", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_no", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "5f22bdc4-5219-4cc3-96bb-8e8800dff627", "cand_id": "523d4a45-4808-40b1-8d60-9df67def2658", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "no", "interviewer_email": "ntnbhat9@gmail.com"},
    {"cr_id": "4779d2dc-ac17-427c-bf6d-593de5d7739d", "cand_id": "56fbc23e-9c13-4c9b-9137-a4efccf9ddd5", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_yes", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "924a65a8-58a6-4481-931e-364f89c48f97", "cand_id": "5f74253e-2f96-4578-8473-9580d481b2bb", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "yes", "interviewer_email": "anushachaturvedi18@gmail.com"},
    {"cr_id": "0e361ade-125a-4c45-964f-8132fb75db5f", "cand_id": "648e594d-be1a-47eb-ba1d-db737d54d0f1", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "maybe", "interviewer_email": "anushachaturvedi18@gmail.com"},
    {"cr_id": "2c24456c-7127-4f21-8a00-e94955f8f763", "cand_id": "79219792-bf26-4123-97e2-21a6eafbaf9f", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "yes", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "02c9ebea-3069-4c40-8e90-35276163f53c", "cand_id": "85528ddc-7c77-4c1a-8334-487deecc9700", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "yes", "interviewer_email": "anushachaturvedi18@gmail.com"},
    {"cr_id": "8933f318-62d8-4810-b242-31eb8c6b7e95", "cand_id": "875fb534-d913-4930-bfa9-ec5a33502272", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "maybe", "interviewer_email": "anushachaturvedi18@gmail.com"},
    {"cr_id": "18ad55cf-99a4-44e0-abce-9a3e4a1ec28c", "cand_id": "9963291e-9874-48b7-b1e9-ab3e95d6be03", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_no", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "4a68fe84-bad6-4182-b6ff-780c2c1dc305", "cand_id": "a2b155dd-bb49-43e6-9fd2-53fad77f4437", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_no", "interviewer_email": "rishitchaturvedi@gmail.com"},
    {"cr_id": "5b21ea80-4a72-4287-b985-157cfeac2c1d", "cand_id": "a539d7dd-28c6-4153-9656-d10f7216dc6f", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "no", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "a27cef90-909f-400d-8dc6-158f71a4401c", "cand_id": "abc82de6-8470-49ef-ab2c-0c3c545bad08", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_yes", "interviewer_email": None},
    {"cr_id": "4c17d3ed-0def-429a-9b5f-4402d73999fe", "cand_id": "c12f2276-624b-43df-ada0-cec4d56a55a3", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_no", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "2b5130ce-9762-4ca5-bdb9-7965c9019d50", "cand_id": "c1423b50-92e4-4a9f-a129-71733a643698", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "yes", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "f63ef2c8-8853-416e-9716-1495db7d432f", "cand_id": "c2d7238d-1a07-413c-a541-40c92eded8b0", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "maybe", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "e6b99976-f1f8-43c5-ad15-220e9c0ade24", "cand_id": "c35114f0-c0da-42ad-8e0e-19dfd8bacf1c", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_yes", "interviewer_email": "anushachaturvedi18@gmail.com"},
    {"cr_id": "21735b9e-ec90-412e-a2b1-3ac778e94603", "cand_id": "c9b95ec3-1266-4edf-a004-106f5bfaa8e6", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "yes", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "c144bb6a-9313-4671-a7bd-8fbc5f481fc3", "cand_id": "c9c08d24-80db-4cad-a26c-8c7637ca23a9", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_no", "interviewer_email": "ntnbhat9@gmail.com"},
    {"cr_id": "993e89bb-7a13-4625-9c31-c15b2f84e15f", "cand_id": "d61f51ce-cc69-41e9-9bff-3795a9deb2f2", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_no", "interviewer_email": "ntnbhat9@gmail.com"},
    {"cr_id": "df483da7-4156-4924-992c-c05f546ed748", "cand_id": "d987b91f-4639-42a7-8418-3e982fc3a318", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "yes", "interviewer_email": None},
    {"cr_id": "0a8d2ec4-4ccb-499b-a07a-ccda0a93e14c", "cand_id": "e49e49bf-b970-4913-94c5-01d2ef15a2f3", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_no", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "af8d4472-811a-4771-8fe1-5cb63d18f79f", "cand_id": "eb0bd449-3a35-4960-9778-599bac0b560d", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_no", "interviewer_email": "rishitchaturvedi@gmail.com"},
    {"cr_id": "ca7b461b-ea2c-4a71-af89-35811e4b410d", "cand_id": "f03f3f4b-9d7f-4df5-a2bd-7e5804d388fd", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "no", "interviewer_email": None},
    {"cr_id": "a713df78-f56f-40a6-9da3-d76fad8d7243", "cand_id": "f24b68c6-26cd-4085-9673-a36702c72756", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "maybe", "interviewer_email": "bhat.nit@northeastern.edu"},
    {"cr_id": "80ccfc2d-4e06-4c55-967b-ad647078e9db", "cand_id": "f47bb150-a61c-4f70-aab2-6e1cf9011626", "round_id": "06f0f715-5707-4f08-b07a-382e3f3215e4", "rating": "strong_no", "interviewer_email": "rishitchaturvedi@gmail.com"},
]

FEEDBACK_BY_CR: dict[str, list[str]] = {
    "02c9ebea-3069-4c40-8e90-35276163f53c": ["Pricing", "User Empathy", "Product Sense"],
    "0a8d2ec4-4ccb-499b-a07a-ccda0a93e14c": ["Pricing", "User Empathy", "Product Sense"],
    "0e361ade-125a-4c45-964f-8132fb75db5f": ["Product Sense", "User Empathy", "Pricing"],
    "18ad55cf-99a4-44e0-abce-9a3e4a1ec28c": ["User Empathy", "Pricing", "Product Sense"],
    "21735b9e-ec90-412e-a2b1-3ac778e94603": ["User Empathy", "Product Sense", "Pricing"],
    "2905ac19-b671-47e3-99a1-c5d298f03c48": ["Pricing", "Product Sense", "User Empathy"],
    "2b5130ce-9762-4ca5-bdb9-7965c9019d50": ["Product Sense", "Pricing", "User Empathy"],
    "2c24456c-7127-4f21-8a00-e94955f8f763": ["Product Sense", "User Empathy", "Pricing"],
    "433769e4-d1a1-4e98-a047-f5705663484a": ["Pricing", "Product Sense", "User Empathy"],
    "4779d2dc-ac17-427c-bf6d-593de5d7739d": ["Product Sense"],
    "4ccf93bd-c05a-4439-9856-0ac59c5275b8": ["Pricing", "Product Sense"],
    "64d96196-4673-4b6f-a097-785b4bd0c4b1": ["User Empathy"],
    "69db8a37-6836-4870-bbc1-6a8725f641d0": ["Product Sense", "User Empathy", "Pricing"],
    "71d5179e-3cd9-4ce7-b8e8-a12f6f79ed04": ["Product Sense", "User Empathy", "Pricing"],
    "80ccfc2d-4e06-4c55-967b-ad647078e9db": ["Pricing", "Product Sense", "User Empathy"],
    "946c313e-f56b-4ac2-9cba-4093ec39337d": ["Product Sense", "User Empathy", "Pricing"],
    "993e89bb-7a13-4625-9c31-c15b2f84e15f": ["User Empathy", "Product Sense", "Pricing"],
    "a03153a7-13b8-4958-9e40-fccabf266803": ["Pricing", "User Empathy", "Product Sense"],
    "a27cef90-909f-400d-8dc6-158f71a4401c": ["User Empathy", "Product Sense", "Pricing"],
    "c144bb6a-9313-4671-a7bd-8fbc5f481fc3": ["User Empathy", "Pricing"],
    "df483da7-4156-4924-992c-c05f546ed748": ["Pricing", "User Empathy", "Product Sense"],
    "e6b99976-f1f8-43c5-ad15-220e9c0ade24": ["Product Sense", "User Empathy", "Pricing"],
    "e09e2ce8-fba0-4684-9334-fd4941333b35": [],
    "f1f97d13-9b29-4bfe-8a8a-a0330a5801a0": [],
    "4a68fe84-bad6-4182-b6ff-780c2c1dc305": [],
    "5b21ea80-4a72-4287-b985-157cfeac2c1d": [],
    "4c17d3ed-0def-429a-9b5f-4402d73999fe": [],
    "af8d4472-811a-4771-8fe1-5cb63d18f79f": [],
    "ca7b461b-ea2c-4a71-af89-35811e4b410d": [],
    "a713df78-f56f-40a6-9da3-d76fad8d7243": [],
    "f512f263-b101-40b8-b680-9bb963256964": [],
    "8933f318-62d8-4810-b242-31eb8c6b7e95": [],
    "924a65a8-58a6-4481-931e-364f89c48f97": [],
    "5f22bdc4-5219-4cc3-96bb-8e8800dff627": [],
    "f63ef2c8-8853-416e-9716-1495db7d432f": [],
}


def send(client: httpx.Client, event_type: str, payload: dict, headers: dict) -> dict:
    body = {
        "event_type": event_type,
        "org_id": ORG_ID,
        "source_ref": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    resp = client.post("/api/v1/ingest/direct", json=body, headers=headers)
    return resp.json()


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

    print(f"=== Ingesting Product Manager requisition ({REQ_ID}) ===\n")

    print("1. plan_created...")
    plan_payload = {"requisition": REQUISITION, "rounds": ROUNDS}
    result = send(client, "plan_created", plan_payload, headers)
    print(f"   {result['status']}: {result['nodes_created']} nodes, {result['edges_created']} edges")
    total_nodes += result["nodes_created"]
    total_edges += result["edges_created"]
    if result.get("errors"):
        errors.extend(result["errors"])

    print(f"\n2. feedback_completed x {len(INTERVIEWS)}...")
    for i, iv in enumerate(INTERVIEWS):
        cand = CANDIDATES[iv["cand_id"]]
        rd = ROUND_LOOKUP[iv["round_id"]]
        feedback_items = [{"heading": h, "question_id": None} for h in FEEDBACK_BY_CR.get(iv["cr_id"], [])]

        payload = {
            "candidate_round": {
                "id": iv["cr_id"],
                "candidate_id": iv["cand_id"],
                "round_id": iv["round_id"],
                "requisition_id": REQ_ID,
                "rating": iv["rating"],
                "interviewer_email": iv["interviewer_email"],
                "organization_id": ORG_ID,
            },
            "round": {
                "id": rd["id"],
                "name": rd["name"],
                "requisition_id": REQ_ID,
                "category": rd["category"],
                "duration_minutes": rd["duration_minutes"],
                "skills": rd["skills"],
            },
            "requisition": REQUISITION,
            "candidate": {
                "id": iv["cand_id"],
                "name": cand["name"],
                "organization_id": ORG_ID,
                "status": cand["status"],
            },
            "feedback_items": feedback_items,
        }
        result = send(client, "feedback_completed", payload, headers)
        marker = "." if result["status"] == "ingested" else "!"
        print(f"   [{i+1:2d}/{len(INTERVIEWS)}] {cand['name'][:20]:<20s} {iv['rating']:<12s} → {result['status']} ({result['nodes_created']}n/{result['edges_created']}e){marker}")
        total_nodes += result["nodes_created"]
        total_edges += result["edges_created"]
        if result.get("errors"):
            errors.extend(result["errors"])

    decision_candidates = {cid: c for cid, c in CANDIDATES.items() if c["status"] in ("hired", "rejected")}
    print(f"\n3. decision_made x {len(decision_candidates)}...")
    for cid, cand in decision_candidates.items():
        payload = {
            "candidate": {
                "id": cid,
                "name": cand["name"],
                "organization_id": ORG_ID,
                "status": cand["status"],
            },
            "requisition": REQUISITION,
        }
        result = send(client, "decision_made", payload, headers)
        print(f"   {cand['name']:<20s} {cand['status']:<10s} → {result['status']}")
        total_nodes += result["nodes_created"]
        total_edges += result["edges_created"]
        if result.get("errors"):
            errors.extend(result["errors"])

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
