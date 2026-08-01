import re

from pipecat.frames.frames import Frame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

_MD_PATTERNS = [
    (re.compile(r'\*\*\*(.*?)\*\*\*'), r'\1'),
    (re.compile(r'\*\*(.*?)\*\*'), r'\1'),
    (re.compile(r'\*(.*?)\*'), r'\1'),
    (re.compile(r'__(.*?)__'), r'\1'),
    (re.compile(r'~~(.*?)~~'), r'\1'),
    (re.compile(r'`(.*?)`'), r'\1'),
    (re.compile(r'^#{1,6}\s+', re.MULTILINE), ''),
    (re.compile(r'^\s*[-*+]\s+', re.MULTILINE), ''),
    (re.compile(r'^\s*\d+\.\s+', re.MULTILINE), ''),
    (re.compile(r'\[([^\]]+)\]\([^)]+\)'), r'\1'),
]

_STRAY_STARS = re.compile(r'\*+')


class MarkdownStripper(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and frame.text:
            cleaned = frame.text
            for pattern, replacement in _MD_PATTERNS:
                cleaned = pattern.sub(replacement, cleaned)
            cleaned = _STRAY_STARS.sub('', cleaned)
            frame.text = cleaned

        await self.push_frame(frame, direction)


_MAYZLE_RE = re.compile(r'\bmayz[ue]?l[e]?\b', re.IGNORECASE)


def _mayzle_replace(match: re.Match) -> str:
    word = match.group(0)
    if word.isupper():
        return "SCOUT"
    if word[0].isupper():
        return "Scout"
    return "scout"


def normalize_phonetic_name(text: str) -> str:
    return _MAYZLE_RE.sub(_mayzle_replace, text)


class TTSNameNormalizer(FrameProcessor):
    """Replaces phonetic TTS spellings with correct display names in text frames.

    Placed after TTS in the pipeline so TTS gets the phonetic version
    for correct pronunciation, while the UI and context get the proper spelling.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and frame.text:
            frame.text = _MAYZLE_RE.sub(_mayzle_replace, frame.text)

        await self.push_frame(frame, direction)
