from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI


from lib.services.qdrant_search_engine.filter_builder import FilterBuilder
from lib.services.qdrant_search_engine.intent_cache import IntentCache
from lib.services.qdrant_search_engine.intent_extractor import IntentExtractor
from lib.utils.vector_utils import embed_text
from qdrant_client.http.models import (
    Filter,
    FieldCondition,
    MatchValue,
    Condition,
    MatchAny,
)
from lib.core.qdrant_store import QdrantStore


class QdrantSearchEngine:
    def __init__(
        self,
        qdrant_store: QdrantStore,
        intent_cache: IntentCache,
        collection_name: str = "patient_data",
    ):
        self.openai_client = AsyncOpenAI()
        self.qdrant_store = qdrant_store
        self.intent_cache = intent_cache
        self.collection_name = collection_name
        self.intent_extractor = IntentExtractor(self.openai_client)

    async def search(
        self,
        query: str,
        limit: int,
        conversation_id: Optional[str] = None,
        patient_id: Optional[str] = None,
    ) -> Dict[str, Any]:

        # Fetch context intents (if conversation_id is provided)
        context_intents = []
        if conversation_id:
            context_intents = self.intent_cache.get_recent_intents(
                conversation_id
            )

        # Extract structured intent (context-aware if any)
        intent = await self.intent_extractor.extract(query, context_intents)

        # Save this intent for continuity
        if conversation_id:
            self.intent_cache.push_intent(conversation_id, intent)

        # Build Qdrant filter conditions
        filter_conditions = FilterBuilder.build(intent)

        # Generate embedding for semantic search
        embedding = await embed_text(query)

        # Perform search in vector service
        results = await self.search_similar_reports(
            query_embedding=embedding,
            limit=limit,
            filter_conditions=filter_conditions,
            patient_id=patient_id,
            # score_threshold=0.6,
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

    async def search_similar_reports(
        self,
        query_embedding: list[float],
        filter_conditions: Optional[Filter] = None,
        limit: int = 500,
        data_types: Optional[List[str]] = None,
        score_threshold: Optional[float] = None,
        patient_id: Optional[str] = None,
    ):
        """
        Search for reports similar to a given embedding with optional filtering.

        Args:
            query_embedding: Vector embedding for the query.
            filter_conditions: Pre-built Qdrant filter conditions.
            limit: Max number of results to return.
            data_types: Optional list of data_type strings to filter by.
            patient_id: Optional patient ID filter.
            score_threshold: Minimum score for returned results.

        Returns:
            List of matching reports.
        """
        async with self.qdrant_store.get_client() as client:
            default_filter = self._build_filter(data_types, patient_id)
            merged_filter = self._merge_filters(
                filter_conditions, default_filter
            )

            print(f"Searching with filter: {merged_filter}, limit: {limit}")

            return await client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=limit,
                query_filter=merged_filter,
                score_threshold=score_threshold,
            )

    def _build_filter(
        self,
        data_types: Optional[List[str]],
        patient_id: Optional[str],
    ) -> Optional[Filter]:
        """
        Build a Qdrant Filter from optional data_types and patient_id.
        """
        conditions: List[Condition] = []

        if data_types:
            conditions.append(self._create_data_type_condition(data_types))

        if patient_id:
            conditions.append(self._create_patient_id_condition(patient_id))

        if conditions:
            return Filter(must=conditions)

        return None

    def _merge_filters(
        self, base_filter: Optional[Filter], extra_filter: Optional[Filter]
    ) -> Optional[Filter]:
        if base_filter and extra_filter:
            return Filter(
                must=(base_filter.must or []) + (extra_filter.must or []),  # type: ignore
                should=(base_filter.should or [])
                + (extra_filter.should or []),  # type: ignore
                must_not=(base_filter.must_not or [])
                + (extra_filter.must_not or []),  # type: ignore
            )
        return base_filter or extra_filter

    @staticmethod
    def _create_data_type_condition(data_types: List[str]) -> FieldCondition:
        return FieldCondition(key="data_type", match=MatchAny(any=data_types))

    @staticmethod
    def _create_patient_id_condition(patient_id: str) -> FieldCondition:
        return FieldCondition(
            key="patient_id", match=MatchValue(value=patient_id)
        )
