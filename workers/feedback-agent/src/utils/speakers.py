import re


def extract_participant_data_for_identification(segments: list[dict]) -> list[dict]:
    """
    Extract participant data from Recall API segments for speaker identification.

    Returns list of participant objects with:
    - name: Participant's name
    - first_sentences: Up to 5 first spoken sentences
    - is_host: (optional) Boolean if provided by platform (Google Meet)
    - is_tenant: (optional) Boolean derived from Teams participant_type
    """
    participants: dict[str, dict] = {}

    for segment in segments:
        if isinstance(segment, str):
            continue

        participant = segment.get("participant", {})
        name = participant.get("name", "Unknown")

        if name == "Unknown":
            continue

        if name not in participants:
            is_host = participant.get("is_host")

            # Extract is_tenant from Teams extra_data.participant_type
            is_tenant = None
            extra_data = participant.get("extra_data", {})
            teams_data = extra_data.get("microsoft_teams", {})
            if teams_data:
                participant_type = teams_data.get("participant_type")
                if participant_type:
                    # inTenant = org member (likely interviewer)
                    # anonymous/federated/nonFederated = external (likely candidate)
                    is_tenant = participant_type == "inTenant"

            participants[name] = {
                "sentences": [],
                "is_host": is_host,
                "is_tenant": is_tenant,
            }

        if len(participants[name]["sentences"]) >= 5:
            continue

        words = segment.get("words", [])
        if words:
            text = " ".join(w.get("text", "") for w in words).strip()
        else:
            text = segment.get("text", "").strip()

        if not text:
            continue

        sentences = re.split(r'(?<=[.!?])\s+', text)
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and len(participants[name]["sentences"]) < 5:
                participants[name]["sentences"].append(sentence)

    result = []
    for name, data in participants.items():
        if not data["sentences"]:
            continue

        entry = {
            "name": name,
            "first_sentences": data["sentences"],
        }
        if data["is_host"] is not None:
            entry["is_host"] = data["is_host"]
        if data["is_tenant"] is not None:
            entry["is_tenant"] = data["is_tenant"]

        result.append(entry)

    return result


def extract_speakers_from_text(text: str) -> list[str]:
    pattern = r'\[\d+:\d+\]\s*([^:]+):'
    matches = re.findall(pattern, text)
    speakers = []
    for match in matches:
        speaker = match.strip()
        if speaker and speaker not in speakers:
            speakers.append(speaker)
    return speakers


def get_primary_speaker(chunk) -> str:
    speaker_counts = {}
    for utterance in chunk.utterances:
        speaker = utterance.speaker or "Unknown"
        if speaker != "Unknown":
            speaker_counts[speaker] = speaker_counts.get(speaker, 0) + len(utterance.text)

    if speaker_counts:
        return max(speaker_counts, key=speaker_counts.get)

    speakers = extract_speakers_from_text(chunk.text)
    if speakers:
        text_counts = {}
        for speaker in speakers:
            text_counts[speaker] = chunk.text.count(f"] {speaker}:")
        if text_counts:
            return max(text_counts, key=text_counts.get)

    return "Unknown"


def get_all_speakers(chunk) -> list[str]:
    speakers = []
    for utterance in chunk.utterances:
        if utterance.speaker and utterance.speaker not in speakers:
            speakers.append(utterance.speaker)

    if not speakers or speakers == ["Unknown"]:
        speakers = extract_speakers_from_text(chunk.text)

    return speakers if speakers else ["Unknown"]


def extract_speakers(chunks, candidate_name: str) -> tuple[str, str]:
    all_speakers = set()
    for chunk in chunks:
        for utterance in chunk.utterances:
            if utterance.speaker:
                all_speakers.add(utterance.speaker)

    speakers = list(all_speakers)
    candidate = "Unknown"
    interviewer = "Unknown"

    for speaker in speakers:
        if candidate_name.lower() in speaker.lower():
            candidate = speaker
            break

    for speaker in speakers:
        if speaker != candidate:
            interviewer = speaker
            break

    return candidate, interviewer
