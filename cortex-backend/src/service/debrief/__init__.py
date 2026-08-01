"""Debrief skill (spec §8). Stateless, idempotent assembly of a comparative
`DebriefPacket` from Neo4j (value-add intelligence) + Supabase (ground truth).

Each class has one responsibility and constructor-injected deps so it is
independently unit-testable. `DebriefService` orchestrates the pipeline:

    SupabaseScaffold → DebriefGraphReader → DebriefScorer → DebriefSpine
                     → ThemeBuilder → ProseSynthesizer → PacketBuilder
"""

from src.service.debrief.debrief_service import DebriefService
from src.service.debrief.graph_reader import DebriefGraphReader
from src.service.debrief.packet_builder import PacketBuilder
from src.service.debrief.prose_synthesizer import ProseSynthesizer
from src.service.debrief.scorer import DebriefScorer
from src.service.debrief.supabase_scaffold import SupabaseScaffold
from src.service.debrief.theme_builder import ThemeBuilder

__all__ = [
    "DebriefService",
    "DebriefGraphReader",
    "PacketBuilder",
    "ProseSynthesizer",
    "DebriefScorer",
    "SupabaseScaffold",
    "ThemeBuilder",
]
