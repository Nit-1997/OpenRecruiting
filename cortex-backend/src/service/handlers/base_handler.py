from abc import ABC, abstractmethod

from src.model.ingestion import SourceRef
from src.service.graph_ingestion_service import (
    GraphIngestionService,
    IngestionResult,
    Triplet,
)
from src.service.supabase_fetcher import SupabaseFetcher
from src.sync.provenance import Provenance


class BaseHandler(ABC):
    def __init__(self, fetcher: SupabaseFetcher, ingestion_service: GraphIngestionService):
        self._fetcher = fetcher
        self._ingestion_service = ingestion_service

    @abstractmethod
    async def fetch_and_build_triplets(self, source_ref: SourceRef, org_id: str) -> list[Triplet]:
        pass

    @abstractmethod
    def build_triplets_from_payload(self, payload: dict, org_id: str) -> list[Triplet]:
        pass

    async def handle(
        self,
        source_ref: SourceRef,
        org_id: str,
        provenance: Provenance | None = None,
    ) -> IngestionResult:
        triplets = await self.fetch_and_build_triplets(source_ref, org_id)
        return await self._ingestion_service.ingest_triplets(
            triplets, org_id, provenance=provenance
        )

    async def handle_direct(
        self,
        payload: dict,
        org_id: str,
        provenance: Provenance | None = None,
    ) -> IngestionResult:
        triplets = self.build_triplets_from_payload(payload, org_id)
        return await self._ingestion_service.ingest_triplets(
            triplets, org_id, provenance=provenance
        )

    def _validate_org(self, resource_org_id: str | None, request_org_id: str) -> None:
        if resource_org_id and resource_org_id != request_org_id:
            from src.exceptions.handlers import CortexException
            raise CortexException(status_code=403, detail="org_id mismatch: resource belongs to different organization")
