import json
import re


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
        pass

    json_match = re.search(r'\{[\s\S]*\}', response)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    brace_count = 0
    start_idx = None
    for i, char in enumerate(response):
        if char == '{':
            if start_idx is None:
                start_idx = i
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0 and start_idx is not None:
                try:
                    return json.loads(response[start_idx:i+1])
                except json.JSONDecodeError:
                    start_idx = None
                    continue

    raise ValueError(f"Could not parse JSON from response: {response[:200]}...")
