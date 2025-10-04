from typing import Optional

from openai import AsyncOpenAI


from lib.services.cgm_report_service_v2.src.cgm_vector.cgm_search_engine.filter_builder import (
    FilterBuilder,
)
from lib.services.cgm_report_service_v2.src.cgm_vector.cgm_search_engine.intent_extractor import (
    IntentExtractor,
)
from lib.utils.vector_utils import embed_text


class CGMSearchEngine:
    def __init__(self, vector_service):
        self.openai_client = AsyncOpenAI()
        self.vector_service = vector_service
        self.intent_extractor = IntentExtractor(self.openai_client)

    async def search(
        self, query: str, limit: int, patient_id: Optional[str] = None
    ):
        # Extract structured intent
        intent = await self.intent_extractor.extract(query)

        # Build Qdrant filter conditions
        filter_conditions = FilterBuilder.build(intent)

        # Generate embedding for semantic search
        embedding = await embed_text(query)

        # Perform search in vector service
        results = await self.vector_service.search_similar_reports(
            query_embedding=embedding,
            limit=limit,
            filter_conditions=filter_conditions,
            patient_id=patient_id,
        )

        return {
            "query": query,
            "filter_applied": self._serialize_filter(filter_conditions),
            "results": results,
            "intent": intent.model_dump_json(),
        }

    @staticmethod
    def _serialize_filter(filter_conditions) -> Optional[dict]:
        if not filter_conditions:
            return None
        return filter_conditions.model_dump(exclude_none=True)
