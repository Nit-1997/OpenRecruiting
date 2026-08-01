import json
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_datetime(iso_string: str) -> datetime:
    if not iso_string:
        raise ValueError("Empty datetime string")
    normalized = iso_string.replace("Z", "+00:00") if iso_string.endswith("Z") else iso_string
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError(f"Naive datetime (missing timezone): {iso_string}")
    return dt


def names_match(name1: str, name2: str) -> bool:
    if not name1 or not name2:
        return False
    n1 = " ".join(name1.lower().split())
    n2 = " ".join(name2.lower().split())
    if n1 == n2:
        return True
    if n1 in n2 or n2 in n1:
        return True
    parts1 = n1.split()
    parts2 = n2.split()
    if parts1 and parts2 and parts1[0] == parts2[0]:
        return True
    return False


def parse_json_response(response: str) -> dict:
    response = response.strip()
    if response.startswith("```json"):
        response = response[7:]
    if response.startswith("```"):
        response = response[3:]
    if "```" in response:
        response = response.split("```")[0]
    response = response.strip()
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(response[start:end])
        raise
