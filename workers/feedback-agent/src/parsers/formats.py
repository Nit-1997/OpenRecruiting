from enum import Enum, auto


class TranscriptFormat(Enum):
    PLAIN_TEXT = auto()
    SPEAKER_LABELED = auto()
    TIMESTAMPED_JSON = auto()
    RECALL_API = auto()
