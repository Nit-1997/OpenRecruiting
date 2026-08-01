from datetime import timedelta
from typing import Optional

from src.models.chunk import Chunk, Utterance
from src.services.embedding import EmbeddingService
from src.chunking.config import ChunkingConfig
from src.chunking.sentence_splitter import SentenceSplitter, Sentence
from src.chunking.semantic_boundary import SemanticBoundaryDetector


class SemanticChunker:
    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        config: Optional[ChunkingConfig] = None
    ):
        self._embedder = embedding_service or EmbeddingService()
        self._config = config or ChunkingConfig()
        self._splitter = SentenceSplitter()
        self._detector = SemanticBoundaryDetector(self._embedder, self._config)

    def chunk(self, utterances: list[Utterance]) -> list[Chunk]:
        """
        Chunk utterances into semantically coherent Chunks.

        Pipeline:
        1. Split utterances into sentences
        2. Detect semantic breakpoints
        3. Refine with speaker turns
        4. Assemble chunks respecting size constraints
        """
        if not utterances:
            return []

        sentences = self._splitter.split_utterances(utterances)
        if not sentences:
            return []

        sentence_texts = [s.text for s in sentences]
        breakpoints = self._detector.detect_breakpoints(sentence_texts)

        speakers = [s.speaker for s in sentences]
        breakpoints = self._detector.refine_with_speaker_turns(
            breakpoints, speakers
        )

        chunks = self._assemble_chunks(sentences, breakpoints)

        return chunks

    def _assemble_chunks(
        self,
        sentences: list[Sentence],
        breakpoints: list[int]
    ) -> list[Chunk]:
        """Assemble sentences into chunks based on breakpoints and size constraints."""
        chunks: list[Chunk] = []
        current_sentences: list[Sentence] = []
        current_tokens = 0
        chunk_id = 0

        breakpoint_set = set(breakpoints)

        def flush_chunk() -> None:
            nonlocal chunks, current_sentences, current_tokens, chunk_id
            if not current_sentences:
                return

            total_tokens = sum(s.token_count for s in current_sentences)

            speakers = set(s.speaker for s in current_sentences)
            if len(speakers) == 1 and total_tokens > self._config.max_chunk_size:
                sub_chunks = self._sub_chunk_large_turn(current_sentences, chunk_id)
                chunks.extend(sub_chunks)
                chunk_id += len(sub_chunks)
            else:
                chunk = self._create_chunk(current_sentences, chunk_id)
                chunks.append(chunk)
                chunk_id += 1

            current_sentences = []
            current_tokens = 0

        for i, sentence in enumerate(sentences):
            should_break = False

            if i in breakpoint_set and current_tokens >= self._config.min_chunk_size:
                should_break = True

            if current_tokens + sentence.token_count > self._config.max_chunk_size:
                should_break = True

            if (current_tokens >= self._config.target_chunk_size and
                current_sentences and
                current_sentences[-1].speaker != sentence.speaker):
                should_break = True

            if should_break:
                flush_chunk()

            current_sentences.append(sentence)
            current_tokens += sentence.token_count

        flush_chunk()

        return chunks

    def _sub_chunk_large_turn(
        self,
        sentences: list[Sentence],
        start_chunk_id: int
    ) -> list[Chunk]:
        """
        Sub-chunk a speaker turn that exceeds max_chunk_size.

        Splits at sentence boundaries while respecting target size.
        All sub-chunks maintain the same speaker attribution.
        """
        if not sentences:
            return []

        chunks: list[Chunk] = []
        current_sentences: list[Sentence] = []
        current_tokens = 0
        chunk_id = start_chunk_id

        for sentence in sentences:
            if sentence.token_count > self._config.max_chunk_size:
                if current_sentences:
                    chunks.append(self._create_chunk(current_sentences, chunk_id))
                    chunk_id += 1
                    current_sentences = []
                    current_tokens = 0
                chunks.append(self._create_chunk([sentence], chunk_id))
                chunk_id += 1
                continue

            if current_tokens + sentence.token_count > self._config.target_chunk_size:
                if current_sentences:
                    chunks.append(self._create_chunk(current_sentences, chunk_id))
                    chunk_id += 1
                current_sentences = [sentence]
                current_tokens = sentence.token_count
            else:
                current_sentences.append(sentence)
                current_tokens += sentence.token_count

        if current_sentences:
            chunks.append(self._create_chunk(current_sentences, chunk_id))

        return chunks

    def _create_chunk(
        self,
        sentences: list[Sentence],
        chunk_id: int
    ) -> Chunk:
        """Create a Chunk from a list of sentences."""
        text = " ".join(s.text for s in sentences)
        token_count = sum(s.token_count for s in sentences)

        utterances = self._sentences_to_utterances(sentences)

        start_time = None
        end_time = None
        for s in sentences:
            if s.start_time is not None and start_time is None:
                start_time = s.start_time
            if s.end_time is not None:
                end_time = s.end_time

        return Chunk(
            id=f"chunk_{chunk_id:04d}",
            text=text,
            token_count=token_count,
            utterances=utterances,
            start_time=timedelta(seconds=start_time) if start_time else None,
            end_time=timedelta(seconds=end_time) if end_time else None
        )

    def _sentences_to_utterances(
        self,
        sentences: list[Sentence]
    ) -> list[Utterance]:
        """Group sentences back into utterances by speaker."""
        if not sentences:
            return []

        utterances: list[Utterance] = []
        current_speaker = sentences[0].speaker
        current_texts: list[str] = []
        current_start = sentences[0].start_time
        current_end = sentences[0].end_time

        for sentence in sentences:
            if sentence.speaker != current_speaker:
                if current_texts:
                    utterances.append(Utterance(
                        text=" ".join(current_texts),
                        speaker=current_speaker,
                        start_time=(
                            timedelta(seconds=current_start)
                            if current_start else None
                        ),
                        end_time=(
                            timedelta(seconds=current_end)
                            if current_end else None
                        )
                    ))
                current_speaker = sentence.speaker
                current_texts = [sentence.text]
                current_start = sentence.start_time
                current_end = sentence.end_time
            else:
                current_texts.append(sentence.text)
                if sentence.end_time is not None:
                    current_end = sentence.end_time

        if current_texts:
            utterances.append(Utterance(
                text=" ".join(current_texts),
                speaker=current_speaker,
                start_time=(
                    timedelta(seconds=current_start)
                    if current_start else None
                ),
                end_time=(
                    timedelta(seconds=current_end)
                    if current_end else None
                )
            ))

        return utterances
