from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI


from lib.services.qdrant_search_engine.filter_builder import FilterBuilder
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
        collection_name: str = "patient_data",
    ):
        self.openai_client = AsyncOpenAI()
        self.qdrant_store = qdrant_store
        self.collection_name = collection_name
        self.intent_extractor = IntentExtractor(self.openai_client)

    async def search(
        self,
        query: str,
        limit: int,
        conversation_id: Optional[str] = None,
        patient_ids: Optional[List[str]] = None,
        report_id: Optional[str] = None,
        data_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:

        # Get previous intents for continuity
        context_intents = []

        # Extract intent
        intent = await self.intent_extractor.extract(query, context_intents)

        # Build filters
        intent_filter = FilterBuilder.build(intent)
        extra_filter = self._build_filter(
            data_types=data_types, patient_ids=patient_ids, report_id=report_id
        )
        merged_filter = self._merge_filters(intent_filter, extra_filter)

        # Generate embedding for semantic search
        embedding = await embed_text(query)

        # Perform search in vector service
        results = await self.search_similar_reports(
            query_embedding=embedding,
            limit=limit,
            filter_conditions=merged_filter,
            # score_threshold=0.6,
        )

        return {
            "query": query,
            "filter_applied": self._serialize_filter(merged_filter),
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
        score_threshold: Optional[float] = None,
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
            print(
                f"Searching with filter: {filter_conditions}, limit: {limit}"
            )

            return await client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=limit,
                query_filter=filter_conditions,
                score_threshold=score_threshold,
            )

    def _build_filter(
        self,
        data_types: Optional[List[str]],
        patient_ids: Optional[List[str]] = None,
        report_id: Optional[str] = None,
    ) -> Optional[Filter]:
        """
        Build a Qdrant Filter from optional data_types and patient_id.
        """
        conditions: List[Condition] = []

        if data_types:
            conditions.append(
                FieldCondition(key="data_type", match=MatchAny(any=data_types))
            )

        if patient_ids:
            # supports one or many patient IDs
            if len(patient_ids) == 1:
                conditions.append(
                    FieldCondition(
                        key="patient_id",
                        match=MatchValue(value=patient_ids[0]),
                    )
                )
            else:
                conditions.append(
                    FieldCondition(
                        key="patient_id", match=MatchAny(any=patient_ids)
                    )
                )

        if report_id:
            conditions.append(
                FieldCondition(
                    key="report_id", match=MatchValue(value=report_id)
                )
            )

        return Filter(must=conditions) if conditions else None

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
