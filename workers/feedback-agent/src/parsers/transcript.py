from dataclasses import dataclass
from datetime import timedelta
import json
import re
from typing import Callable

from src.models.chunk import Utterance
from src.parsers.formats import TranscriptFormat


@dataclass
class ParseResult:
    utterances: list[Utterance]
    format_detected: TranscriptFormat
    speaker_count: int
    has_timestamps: bool


class TranscriptParser:
    SPEAKER_PATTERN = re.compile(
        r"^(?P<speaker>[A-Z][a-zA-Z\s\-\']+):\s*(?P<text>.+)$",
        re.MULTILINE
    )

    def parse(
        self, content: str, format_hint: TranscriptFormat | None = None
    ) -> ParseResult:
        content = content.strip()
        if not content:
            raise ValueError("Empty transcript content")

        fmt = format_hint or self._detect_format(content)

        parser_map: dict[TranscriptFormat, Callable[[str], list[Utterance]]] = {
            TranscriptFormat.PLAIN_TEXT: self._parse_plain_text,
            TranscriptFormat.SPEAKER_LABELED: self._parse_speaker_labeled,
            TranscriptFormat.TIMESTAMPED_JSON: self._parse_timestamped_json,
            TranscriptFormat.RECALL_API: self._parse_recall_api,
        }

        utterances = parser_map[fmt](content)

        return ParseResult(
            utterances=utterances,
            format_detected=fmt,
            speaker_count=len(set(u.speaker for u in utterances if u.speaker)),
            has_timestamps=any(u.start_time is not None for u in utterances),
        )

    def _detect_format(self, content: str) -> TranscriptFormat:
        if content.startswith("[") or content.startswith("{"):
            try:
                data = json.loads(content)
                if self._is_recall_format(data):
                    return TranscriptFormat.RECALL_API
                return TranscriptFormat.TIMESTAMPED_JSON
            except json.JSONDecodeError:
                pass

        if self.SPEAKER_PATTERN.search(content):
            return TranscriptFormat.SPEAKER_LABELED

        return TranscriptFormat.PLAIN_TEXT

    def _is_recall_format(self, data: list | dict) -> bool:
        if isinstance(data, list) and len(data) > 0:
            item = data[0]
            return (
                isinstance(item, dict)
                and "participant" in item
                and "words" in item
            )
        return False

    def _parse_plain_text(self, content: str) -> list[Utterance]:
        paragraphs = re.split(r"\n\s*\n", content)
        return [
            Utterance(text=p.strip(), speaker=None)
            for p in paragraphs
            if p.strip()
        ]

    def _parse_speaker_labeled(self, content: str) -> list[Utterance]:
        utterances = []
        current_speaker = None
        current_lines: list[str] = []

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue

            match = self.SPEAKER_PATTERN.match(line)
            if match:
                if current_lines:
                    utterances.append(
                        Utterance(
                            text=" ".join(current_lines),
                            speaker=current_speaker,
                        )
                    )
                current_speaker = match.group("speaker").strip()
                text = match.group("text").strip()
                current_lines = [text] if text else []
            else:
                current_lines.append(line)

        if current_lines:
            utterances.append(
                Utterance(
                    text=" ".join(current_lines),
                    speaker=current_speaker,
                )
            )

        return [u for u in utterances if u.text.strip()]

    def _parse_timestamped_json(self, content: str) -> list[Utterance]:
        data = json.loads(content)
        utterances = []

        items = data if isinstance(data, list) else data.get("utterances", [])

        for item in items:
            utterances.append(
                Utterance(
                    text=item.get("text", ""),
                    speaker=item.get("speaker"),
                    start_time=self._parse_time(
                        item.get("start_time") or item.get("start")
                    ),
                    end_time=self._parse_time(
                        item.get("end_time") or item.get("end")
                    ),
                )
            )

        return [u for u in utterances if u.text.strip()]

    def _parse_recall_api(self, content: str) -> list[Utterance]:
        data = json.loads(content)
        utterances = []

        for segment in data:
            participant = segment.get("participant", {})
            speaker = participant.get("name")

            segment_words = []
            segment_start = None
            segment_end = None

            for word in segment.get("words", []):
                text = word.get("text", "")
                if not text.strip():
                    continue

                start_ts = word.get("start_timestamp", {})
                end_ts = word.get("end_timestamp", {})

                word_start = self._parse_recall_timestamp(start_ts)
                word_end = self._parse_recall_timestamp(end_ts)

                if segment_start is None:
                    segment_start = word_start
                segment_end = word_end
                segment_words.append(text)

            if segment_words:
                utterances.append(
                    Utterance(
                        text=" ".join(segment_words),
                        speaker=speaker,
                        start_time=segment_start,
                        end_time=segment_end,
                    )
                )

        return utterances

    def _parse_recall_timestamp(self, ts: dict | None) -> timedelta | None:
        if not ts:
            return None
        if "relative" in ts:
            return timedelta(seconds=float(ts["relative"]))
        return None

    def _parse_time(self, value) -> timedelta | None:
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return timedelta(seconds=float(value))

        if isinstance(value, str):
            try:
                return timedelta(seconds=float(value))
            except ValueError:
                pass

            match = re.match(r"(\d+):(\d+):(\d+)(?:\.(\d+))?", value)
            if match:
                h, m, s = int(match[1]), int(match[2]), int(match[3])
                ms = int(match[4]) if match[4] else 0
                return timedelta(hours=h, minutes=m, seconds=s, milliseconds=ms)

        return None
