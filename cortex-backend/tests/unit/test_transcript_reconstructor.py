from src.service.transcript_reconstructor import (
    classify_speaker,
    reconstruct_conversation,
    reconstruct_with_roles,
)


def test_reconstruct_basic_segments():
    segments = [
        {"participant": {"name": "Priya"}, "words": [{"text": "Tell"}, {"text": "me"}]},
        {"participant": {"name": "Alice"}, "words": [{"text": "I"}, {"text": "worked"}]},
    ]
    result = reconstruct_conversation(segments)
    assert result == "Priya: Tell me\nAlice: I worked"


def test_reconstruct_skips_empty_segments():
    segments = [
        {"participant": {"name": "Priya"}, "words": [{"text": "Hello"}]},
        {"participant": {"name": "Alice"}, "words": [{"text": "  "}]},
        {"participant": {"name": "Priya"}, "words": [{"text": "Next"}]},
    ]
    result = reconstruct_conversation(segments)
    assert "Alice" not in result


def test_reconstruct_empty_segments():
    assert reconstruct_conversation([]) == ""


def test_reconstruct_handles_missing_words():
    segments = [
        {"participant": {"name": "Priya"}, "words": []},
        {"participant": {"name": "Alice"}, "words": [{"text": "Hello"}]},
    ]
    result = reconstruct_conversation(segments)
    assert result == "Alice: Hello"


def test_reconstruct_handles_segments_without_words_key():
    segments = [
        {"participant": {"name": "Bot"}},
        {"participant": {"name": "Alice"}, "words": [{"text": "Hi"}]},
    ]
    result = reconstruct_conversation(segments)
    assert result == "Alice: Hi"


def test_classify_speaker_exact_match():
    assert classify_speaker("Mohit Jaspara", "Mohit Jaspara", "Priya Raman") == "CANDIDATE"
    assert classify_speaker("Priya Raman", "Mohit Jaspara", "Priya Raman") == "INTERVIEWER"


def test_classify_speaker_token_overlap():
    assert classify_speaker("Mohit", "Mohit Jaspara", "Priya Raman") == "CANDIDATE"
    assert classify_speaker("Priya Ramanujam", "Mohit Jaspara", "Priya Raman") == "INTERVIEWER"


def test_classify_speaker_unknown_returns_other():
    assert classify_speaker("Random Bot", "Mohit Jaspara", "Priya Raman") == "OTHER"
    assert classify_speaker("", "Mohit Jaspara", "Priya Raman") == "OTHER"


def test_classify_speaker_handles_missing_target_names():
    assert classify_speaker("Mohit Jaspara", None, None) == "OTHER"
    assert classify_speaker("Mohit Jaspara", "Mohit Jaspara", None) == "CANDIDATE"
    assert classify_speaker("Priya", None, "Priya Raman") == "INTERVIEWER"


def test_classify_speaker_picks_best_match_on_conflict():
    assert classify_speaker("John Smith", "John Smith", "John Doe") == "CANDIDATE"
    assert classify_speaker("John Doe", "John Smith", "John Doe") == "INTERVIEWER"


def test_classify_speaker_returns_other_on_ambiguous_token():
    assert classify_speaker("John", "John Smith", "John Doe") == "OTHER"


def test_reconstruct_with_roles_tags_each_turn():
    segments = [
        {"participant": {"name": "Priya Raman"}, "words": [{"text": "Tell"}, {"text": "me"}, {"text": "about"}, {"text": "your"}, {"text": "work"}]},
        {"participant": {"name": "Mohit Jaspara"}, "words": [{"text": "I"}, {"text": "led"}, {"text": "API"}, {"text": "platform"}]},
        {"participant": {"name": "Random Bot"}, "words": [{"text": "Recording"}, {"text": "started"}]},
    ]
    result = reconstruct_with_roles(segments, candidate_name="Mohit Jaspara", interviewer_name="Priya Raman")
    lines = result.split("\n")
    assert lines[0].startswith("[INTERVIEWER] Priya Raman:")
    assert lines[1].startswith("[CANDIDATE] Mohit Jaspara:")
    assert lines[2].startswith("[OTHER] Random Bot:")


def test_reconstruct_with_roles_handles_missing_names():
    segments = [
        {"participant": {"name": "Some Person"}, "words": [{"text": "Hello"}]},
    ]
    result = reconstruct_with_roles(segments, candidate_name=None, interviewer_name=None)
    assert result == "[OTHER] Some Person: Hello"


def test_reconstruct_with_roles_skips_empty_text():
    segments = [
        {"participant": {"name": "Mohit Jaspara"}, "words": [{"text": "  "}]},
        {"participant": {"name": "Mohit Jaspara"}, "words": [{"text": "Real"}, {"text": "answer"}]},
    ]
    result = reconstruct_with_roles(segments, candidate_name="Mohit Jaspara", interviewer_name="Priya")
    assert result == "[CANDIDATE] Mohit Jaspara: Real answer"
