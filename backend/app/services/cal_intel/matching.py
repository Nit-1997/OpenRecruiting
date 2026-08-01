"""Pure Calendar-Intelligence heuristics.

No DB, no network, no Slack. Title/candidate-name extraction + fuzzy match,
attendee/email hints, timezone coercion, role/location similarity, fuzzy round
match, requisition scoring, and time formatting. Moved verbatim out of
``calendar_intelligence_service`` (which now re-exports these names so existing
import sites keep working).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Optional
from zoneinfo import ZoneInfo, available_timezones


IANA_TIMEZONE_BY_LOWER = {tz.lower(): tz for tz in available_timezones()}
_TEXT_STOP_WORDS = {"the", "and", "for", "with", "from", "this", "that", "role", "round", "interview"}
_ROLE_GENERIC_WORDS = {
    "role", "position", "opening", "job", "senior", "jr", "junior",
    "staff", "lead", "principal",
}
_CANDIDATE_HINT_STOP_WORDS = {
    "interview", "interviewer", "candidate", "round", "screen", "call",
    "meeting", "openrecruiting", "team", "sync", "discussion", "with", "for", "and",
}


def _email_local_to_name(email: str) -> str:
    local = email.split("@")[0] if "@" in email else email
    parts = re.split(r"[._\-+]", local)
    words = [p for p in parts if p]
    if not words:
        return ""
    return " ".join(w.capitalize() for w in words)


def _extract_emails_from_text(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)


def _extract_candidate_from_title(title: str) -> tuple[str, str]:
    """Best-effort candidate fallback when attendee metadata is weak."""
    if not title:
        return "", ""

    emails = _extract_emails_from_text(title)
    candidate_email = emails[0].lower() if emails else ""

    cleaned = title
    for email in emails:
        cleaned = cleaned.replace(email, " ")
    chunks = [c.strip() for c in re.split(r"[<>|/]", cleaned) if c.strip()]

    candidate_name = ""
    for chunk in chunks:
        normalized = re.sub(r"\s+", " ", chunk).strip()
        if not normalized:
            continue
        chunk_words = [w for w in re.findall(r"[A-Za-z]+", normalized)]
        if not chunk_words:
            continue
        lowered = {w.lower() for w in chunk_words}
        if lowered & _CANDIDATE_HINT_STOP_WORDS:
            continue
        if len(chunk_words) > 5:
            continue
        candidate_name = " ".join(chunk_words).strip()
        if candidate_name:
            break

    return candidate_name, candidate_email


def _normalize_person_name(value: str) -> str:
    return re.sub(r"[^a-z]", "", str(value or "").lower())


def _extract_title_name_candidates(title: str) -> list[str]:
    if not title:
        return []

    cleaned = title
    for email in _extract_emails_from_text(title):
        cleaned = cleaned.replace(email, " ")

    head = cleaned.split("|", 1)[0]
    if "<>" in head:
        chunks = [c.strip() for c in head.split("<>") if c.strip()]
    else:
        chunks = [c.strip() for c in re.split(r"[<>/]", head) if c.strip()]

    names: list[str] = []
    for chunk in chunks:
        normalized = re.sub(r"\s+", " ", chunk).strip()
        if not normalized:
            continue
        words = [w for w in re.findall(r"[A-Za-z]+", normalized)]
        if not words:
            continue
        lowered = {w.lower() for w in words}
        if lowered & _CANDIDATE_HINT_STOP_WORDS:
            continue
        if len(words) > 4:
            continue
        candidate = " ".join(words).strip()
        if candidate:
            names.append(candidate)

    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = _normalize_person_name(name)
        if key and key not in seen:
            deduped.append(name)
            seen.add(key)
    return deduped


def _internal_name_hints(internal_attendees: list[dict]) -> set[str]:
    return _attendee_name_hints(internal_attendees)


def _email_local_hints(email: str) -> set[str]:
    local = (email.split("@")[0] if "@" in email else email).lower()
    if not local:
        return set()
    raw_parts = [p for p in re.split(r"[._\-+]", local) if p]
    cleaned_parts = [re.sub(r"\d+", "", p) for p in raw_parts]
    hints = {p for p in cleaned_parts if p}
    normalized_local = _normalize_person_name(local)
    if normalized_local:
        hints.add(normalized_local)
    if len(hints) == 1:
        only = next(iter(hints))
        if len(only) >= 3:
            hints.add(only[:3])
    return hints


def _attendee_name_hints(attendees: list[dict], email: str = "") -> set[str]:
    hints: set[str] = set()
    target_email = str(email or "").strip().lower()
    for attendee in (attendees or []):
        if not isinstance(attendee, dict):
            continue
        att_email = str(attendee.get("email") or "").strip().lower()
        if target_email and att_email != target_email:
            continue

        display_name = str(attendee.get("display_name") or "").strip()
        if display_name:
            for token in re.findall(r"[A-Za-z]+", display_name.lower()):
                if token:
                    hints.add(token)
            normalized = _normalize_person_name(display_name)
            if normalized:
                hints.add(normalized)

        if att_email:
            hints.update(_email_local_hints(att_email))

    if target_email and target_email not in {str(a.get("email") or "").strip().lower() for a in (attendees or []) if isinstance(a, dict)}:
        hints.update(_email_local_hints(target_email))
    return hints


def _name_hint_score(name: str, hints: set[str]) -> float:
    if not name or not hints:
        return 0.0
    name_tokens = [t for t in re.findall(r"[A-Za-z]+", name.lower()) if t]
    if not name_tokens:
        return 0.0
    score = 0.0
    for token in name_tokens:
        if token in hints:
            score = max(score, 1.0)
            continue
        for hint in hints:
            if not hint:
                continue
            score = max(score, SequenceMatcher(None, token, hint).ratio())
    return score


def _best_title_name_match(names: list[str], hints: set[str]) -> tuple[str, float]:
    best_name = ""
    best_score = 0.0
    for name in names:
        score = _name_hint_score(name, hints)
        if score > best_score:
            best_name = name
            best_score = score
    return best_name, best_score


def _extract_candidate_name_from_title(
    title: str,
    internal_attendees: list[dict],
    *,
    external_attendees: list[dict] | None = None,
    candidate_email: str = "",
) -> str:
    names = _extract_title_name_candidates(title)
    if not names:
        fallback_name, _ = _extract_candidate_from_title(title)
        if fallback_name:
            names = [fallback_name]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]

    internal_hints = _attendee_name_hints(internal_attendees)
    external_hints = _attendee_name_hints(external_attendees or [], email=candidate_email)
    internal_name, internal_score = _best_title_name_match(names, internal_hints)
    external_name, external_score = _best_title_name_match(names, external_hints)

    if internal_score >= 0.88 and len(names) == 2 and internal_name:
        for name in names:
            if _normalize_person_name(name) != _normalize_person_name(internal_name):
                return name

    if external_score >= 0.88 and external_name:
        return external_name

    if (
        len(names) == 2
        and internal_score >= 0.75
        and external_score >= 0.75
        and _normalize_person_name(internal_name) != _normalize_person_name(external_name)
    ):
        return external_name

    # Ambiguous title tokens: don't guess and drift names.
    return ""


def _extract_interviewer_from_title(title: str) -> str:
    if not title:
        return ""
    cleaned = title
    for email in _extract_emails_from_text(title):
        cleaned = cleaned.replace(email, " ")
    if "<>" not in cleaned:
        return ""
    interviewer_hint = cleaned.split("<>", 1)[0]
    interviewer_hint = re.split(r"[|/]", interviewer_hint, maxsplit=1)[0]
    interviewer_hint = re.sub(r"(?i)\binterview\b[:\-\s]*", " ", interviewer_hint)
    words = re.findall(r"[A-Za-z][A-Za-z'’\-]*", interviewer_hint)
    if not words:
        return ""
    return " ".join(words[:4]).strip()


def _extract_interviewer_name_from_title(
    title: str,
    internal_attendees: list[dict],
    *,
    interviewer_email: str = "",
    candidate_name: str = "",
) -> str:
    names = _extract_title_name_candidates(title)
    if not names:
        return _extract_interviewer_from_title(title)

    interviewer_hints = _attendee_name_hints(internal_attendees, email=interviewer_email)
    interviewer_name, interviewer_score = _best_title_name_match(names, interviewer_hints)
    if interviewer_score >= 0.88 and interviewer_name:
        return interviewer_name

    if len(names) == 2 and candidate_name:
        candidate_norm = _normalize_person_name(candidate_name)
        for name in names:
            if _normalize_person_name(name) != candidate_norm:
                return name

    return _extract_interviewer_from_title(title)


def email_affinity_lookup(
    external_emails: set[str], candidates: list[dict]
) -> dict[str, set[str]]:
    email_to_reqs: dict[str, set[str]] = {}
    for c in candidates:
        email = (c.get("email") or "").lower()
        if email and email in external_emails:
            email_to_reqs.setdefault(email, set()).add(str(c["requisition_id"]))
    return email_to_reqs


ROLE_SIMILARITY_THRESHOLD = 0.6
LOCATION_SIMILARITY_THRESHOLD = 0.4
ROUND_SIMILARITY_THRESHOLD = 0.5
MAX_NARROWED_SCORE_HINTS = 25
MULTI_EMAIL_AFFINITY_BOOST = 0.08

_ROUND_STOP_WORDS = {"round", "interview", "the", "and", "&", "a", "an", "|", "-", "of"}
_LOCATION_STOP_WORDS = {
    # Countries / regions
    "india", "usa", "us", "uk", "eu", "canada",
    # Work mode
    "remote", "onsite", "hybrid",
    # Building descriptors
    "office", "hq", "headquarters", "campus",
    # US state abbreviations (non-ambiguous ones only)
    "ca", "ny", "tx", "wa", "fl", "il", "ma", "pa", "va", "md",
    "nj", "ct", "nc", "ga", "oh", "mi", "az", "co", "nv", "ut",
    "mn", "wi", "tn", "sc", "ky", "la", "al", "ia", "ks", "ar",
    "ms", "dc", "nm", "ne", "nh", "me", "ri", "mt", "de", "hi",
    "ak", "wv", "wy", "sd", "nd", "vt", "ok",
}
_LOCATION_ALIASES = {
    "bengaluru": "bangalore",
    "bangalore": "bangalore",
    "blr": "bangalore",
    "nyc": "new york",
    "new york city": "new york",
    "sf": "san francisco",
}
_SHORT_PREFIX_ROLE_HEADS = {
    "manager", "engineer", "developer", "designer", "analyst",
    "scientist", "specialist", "consultant", "architect", "recruiter",
}


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _role_tokens(value: str) -> list[str]:
    if not value:
        return []
    return [
        token for token in re.findall(r"[a-z0-9]+", value.lower())
        if token and token not in _ROLE_GENERIC_WORDS
    ]


def _is_short_prefixed_role(tokens: list[str]) -> bool:
    return (
        len(tokens) == 2
        and tokens[0].isalpha()
        and 1 <= len(tokens[0]) <= 3
        and tokens[1] in _SHORT_PREFIX_ROLE_HEADS
    )


def _role_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0

    seq_sim = _similarity(a, b)
    a_tokens = _role_tokens(a)
    b_tokens = _role_tokens(b)
    if not a_tokens or not b_tokens:
        return seq_sim

    # Guard against false positives like "PR Manager" vs "MR/LR/KR Manager".
    if (
        _is_short_prefixed_role(a_tokens)
        and _is_short_prefixed_role(b_tokens)
        and a_tokens[1] == b_tokens[1]
        and a_tokens[0] != b_tokens[0]
    ):
        return 0.0

    a_set = set(a_tokens)
    b_set = set(b_tokens)
    overlap = len(a_set & b_set)
    if overlap == 0:
        return seq_sim * 0.6

    jaccard = overlap / len(a_set | b_set)
    containment = overlap / len(a_set)
    blended = (0.55 * seq_sim) + (0.30 * containment) + (0.15 * jaccard)
    return max(seq_sim, blended)


def _canonical_location(value: str) -> str:
    if not value:
        return ""
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    normalized = normalized.replace(";", ",")
    first_part = normalized.split(",")[0].strip()
    if first_part in _LOCATION_ALIASES:
        return _LOCATION_ALIASES[first_part]
    tokens = [
        t for t in re.findall(r"[a-z0-9]+", first_part)
        if t not in _LOCATION_STOP_WORDS
    ]
    cleaned = " ".join(tokens)
    return _LOCATION_ALIASES.get(cleaned, cleaned)


def _location_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0

    a_city = _canonical_location(a)
    b_city = _canonical_location(b)
    if a_city and b_city:
        if a_city == b_city:
            return 1.0
        sim_city = _similarity(a_city, b_city)
        if sim_city >= 0.85:
            return sim_city

    a_tokens = {t for t in re.findall(r"[a-z0-9]+", a.lower()) if t not in _LOCATION_STOP_WORDS}
    b_tokens = {t for t in re.findall(r"[a-z0-9]+", b.lower()) if t not in _LOCATION_STOP_WORDS}
    if not a_tokens or not b_tokens:
        return 0.0

    intersection = a_tokens & b_tokens
    if len(intersection) < 2:
        return 0.0

    union = a_tokens | b_tokens
    return len(intersection) / len(union)


def _text_tokens(value: str) -> set[str]:
    if not value:
        return set()
    return {
        t for t in re.findall(r"[a-z0-9]+", value.lower())
        if len(t) > 2 and t not in _TEXT_STOP_WORDS
    }


def _description_overlap_ratio(target: str, description: str) -> float:
    tgt = _text_tokens(target)
    desc = _text_tokens(description)
    if not tgt or not desc:
        return 0.0
    return len(tgt & desc) / len(tgt)


def _fuzzy_round_match(extracted: str, db_name: str) -> bool:
    if _similarity(extracted, db_name) >= ROUND_SIMILARITY_THRESHOLD:
        return True
    ext_tokens = {w for w in extracted.lower().split() if w not in _ROUND_STOP_WORDS}
    db_tokens = {w for w in db_name.lower().split() if w not in _ROUND_STOP_WORDS}
    if not ext_tokens:
        return False
    overlap = ext_tokens & db_tokens
    return len(overlap) / len(ext_tokens) >= 0.6


def filter_requisitions_by_extracted_fields(
    extracted: dict, requisitions: list[dict], event_location: str = "",
) -> tuple[list[dict], dict]:
    filters = {}
    current = list(requisitions)

    role_name = (extracted.get("role_name") or "").strip()
    if role_name:
        matched = [r for r in current if _role_similarity(role_name, r.get("role_title") or "") >= ROLE_SIMILARITY_THRESHOLD]
        if matched:
            current = matched
            filters["role_name"] = f"matched:{len(matched)}"
        else:
            filters["role_name"] = "no_match"

    location = (extracted.get("location") or event_location or "").strip()
    if location:
        matched = [r for r in current if _location_similarity(location, r.get("role_location") or "") >= LOCATION_SIMILARITY_THRESHOLD]
        if matched:
            current = matched
            filters["location"] = f"matched:{len(matched)}"
        else:
            filters["location"] = "no_match"

    round_name = (extracted.get("round_name") or "").strip()
    if round_name:
        matched = []
        for r in current:
            for rd in (r.get("rounds") or []):
                if _fuzzy_round_match(round_name, rd.get("name") or ""):
                    matched.append(r)
                    break
        if matched:
            current = matched
            filters["round_name"] = f"matched:{len(matched)}"
        else:
            filters["round_name"] = "no_match"

    return current, filters


def score_role_match(
    req: dict, extracted: dict, email_req_ids: set[str], event_location: str = "", event_description: str = "",
) -> tuple[float, Optional[str]]:
    score = 0.0
    matched_round_id = None

    role_name = (extracted.get("role_name") or "").strip()
    if role_name:
        role_sim = _role_similarity(role_name, req.get("role_title") or "")
        if role_sim >= 0.9:
            score += 0.30
        elif role_sim >= ROLE_SIMILARITY_THRESHOLD:
            score += 0.20

    location = (extracted.get("location") or event_location or "").strip()
    if location:
        loc_sim = _location_similarity(location, req.get("role_location") or "")
        if loc_sim >= LOCATION_SIMILARITY_THRESHOLD:
            score += 0.25

    round_name = (extracted.get("round_name") or "").strip()
    if round_name:
        for rd in (req.get("rounds") or []):
            if _fuzzy_round_match(round_name, rd.get("name") or ""):
                score += 0.25
                matched_round_id = str(rd["id"])
                break

    if str(req["id"]) in email_req_ids:
        if len(email_req_ids) <= 1:
            score += 0.20
        else:
            score += MULTI_EMAIL_AFFINITY_BOOST

    desc = (event_description or "").strip()
    if desc:
        role_overlap = _description_overlap_ratio(req.get("role_title") or "", desc)
        if role_overlap >= 0.7:
            score += 0.10
        elif role_overlap >= 0.4:
            score += 0.05

        for rd in (req.get("rounds") or []):
            rd_name = rd.get("name") or ""
            if not rd_name:
                continue
            if _fuzzy_round_match(rd_name, desc) or _description_overlap_ratio(rd_name, desc) >= 0.6:
                score += 0.08
                if matched_round_id is None:
                    matched_round_id = str(rd["id"])
                break

    return score, matched_round_id


def _coerce_timezone_name(timezone_name: str) -> str:
    if not timezone_name:
        return ""
    raw = timezone_name.strip()
    if not raw:
        return ""
    upper = raw.upper()
    aliases = {
        "EST": "America/New_York",
        "EDT": "America/New_York",
        "PST": "America/Los_Angeles",
        "PDT": "America/Los_Angeles",
        "CST": "America/Chicago",
        "CDT": "America/Chicago",
        "MST": "America/Denver",
        "MDT": "America/Denver",
        "IST": "Asia/Kolkata",
        "APAC": "Asia/Singapore",
        "ASIA-PACIFIC": "Asia/Singapore",
        "ASIA PACIFIC": "Asia/Singapore",
        "US/PACIFIC": "America/Los_Angeles",
        "US/EASTERN": "America/New_York",
        "US/CENTRAL": "America/Chicago",
        "US/MOUNTAIN": "America/Denver",
    }
    if upper in aliases:
        return aliases[upper]

    if "PACIFIC" in upper:
        return "America/Los_Angeles"
    if "EASTERN" in upper:
        return "America/New_York"
    if "CENTRAL" in upper:
        return "America/Chicago"
    if "MOUNTAIN" in upper:
        return "America/Denver"

    if "/" in raw and raw.count("/") == 1 and "America/" not in raw and "Asia/" not in raw and "Europe/" not in raw:
        parts = [p.strip().upper() for p in raw.split("/") if p.strip()]
        mapped = [aliases[p] for p in parts if p in aliases]
        unique_mapped = list(dict.fromkeys(mapped))
        if len(unique_mapped) == 1:
            return unique_mapped[0]
        if len(unique_mapped) > 1:
            # Ambiguous display labels like "EST/PST" should fall back to event timezone.
            return ""

    canonical = IANA_TIMEZONE_BY_LOWER.get(raw.lower()) or IANA_TIMEZONE_BY_LOWER.get(raw.replace(" ", "_").lower())
    if canonical:
        return canonical
    return raw


def _format_event_time(val, timezone_name: str = "") -> str:
    if not val:
        return "TBD"
    if isinstance(val, str):
        text = val.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            val = datetime.fromisoformat(text)
        except Exception:
            return "TBD"
    if not isinstance(val, datetime):
        return "TBD"
    dt = val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    tz_to_use = _coerce_timezone_name(timezone_name)
    if tz_to_use:
        try:
            dt = dt.astimezone(ZoneInfo(tz_to_use))
        except Exception:
            pass
    return dt.strftime("%b %d at %I:%M %p")


def format_event_time_for_email(val, timezone_name: str = "") -> str:
    """Format timestamp for email copy with explicit date and timezone."""
    if not val:
        return "TBD"
    if isinstance(val, str):
        text = val.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            val = datetime.fromisoformat(text)
        except Exception:
            return "TBD"
    if not isinstance(val, datetime):
        return "TBD"

    dt = val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    tz_to_use = _coerce_timezone_name(timezone_name)
    if tz_to_use:
        try:
            dt = dt.astimezone(ZoneInfo(tz_to_use))
        except Exception:
            pass
    return dt.strftime("%b %d, %Y at %I:%M %p %Z")


def _format_created_date(created_at: str) -> str:
    if not created_at or not isinstance(created_at, str):
        return ""
    try:
        text = created_at
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt.strftime("%b %d")
    except Exception:
        return ""
