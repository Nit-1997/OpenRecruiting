from dataclasses import dataclass, field
from typing import Optional

import pysbd

from src.models.chunk import Utterance
from src.utils.tokens import count_tokens


@dataclass
class Sentence:
    text: str
    speaker: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    token_count: int = field(default=0)

    def __post_init__(self) -> None:
        if self.token_count == 0:
            self.token_count = count_tokens(self.text)


class SentenceSplitter:
    def __init__(self, language: str = "en") -> None:
        self._segmenter = pysbd.Segmenter(language=language, clean=False)

    def split_text(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []
        return self._segmenter.segment(text)

    def split_utterance(self, utterance: Utterance) -> list[Sentence]:
        sentence_texts = self.split_text(utterance.text)
        sentences = []

        for text in sentence_texts:
            text = text.strip()
            if not text:
                continue

            sentences.append(
                Sentence(
                    text=text,
                    speaker=utterance.speaker,
                    start_time=(
                        utterance.start_time.total_seconds()
                        if utterance.start_time
                        else None
                    ),
                    end_time=(
                        utterance.end_time.total_seconds()
                        if utterance.end_time
                        else None
                    ),
                )
            )

        return sentences

    def split_utterances(self, utterances: list[Utterance]) -> list[Sentence]:
        sentences = []
        for utterance in utterances:
            sentences.extend(self.split_utterance(utterance))
        return sentences
