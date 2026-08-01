def reconstruct_conversation(segments: list[dict]) -> str:
    lines = []
    for seg in segments:
        speaker = seg["participant"]["name"]
        words = seg.get("words") or []
        text = " ".join(w["text"] for w in words)
        if text.strip():
            lines.append(f"{speaker}: {text.strip()}")
    return "\n".join(lines)


def reconstruct_with_roles(
    segments: list[dict],
    candidate_name: str | None,
    interviewer_name: str | None,
) -> str:
    lines = []
    for seg in segments:
        speaker = seg["participant"]["name"]
        words = seg.get("words") or []
        text = " ".join(w["text"] for w in words)
        if not text.strip():
            continue
        role = classify_speaker(speaker, candidate_name, interviewer_name)
        lines.append(f"[{role}] {speaker}: {text.strip()}")
    return "\n".join(lines)


def classify_speaker(
    speaker: str,
    candidate_name: str | None,
    interviewer_name: str | None,
) -> str:
    cand_score = _match_score(speaker, candidate_name)
    inter_score = _match_score(speaker, interviewer_name)
    if cand_score > inter_score and cand_score > 0:
        return "CANDIDATE"
    if inter_score > cand_score and inter_score > 0:
        return "INTERVIEWER"
    return "OTHER"


def _match_score(speaker: str | None, target: str | None) -> int:
    if not speaker or not target:
        return 0
    s = speaker.strip().lower()
    t = target.strip().lower()
    if not s or not t:
        return 0
    if s == t:
        return 1000
    s_tokens = {tok for tok in s.replace(",", " ").split() if len(tok) >= 2}
    t_tokens = {tok for tok in t.replace(",", " ").split() if len(tok) >= 2}
    return len(s_tokens & t_tokens)
