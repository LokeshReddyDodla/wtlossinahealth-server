from typing import Any, Dict, List

from lib.core.mongo_store import MongoStore
from lib.schemas.patient import CorePatientProfile as CorePatientProfileSchema
from lib.services.ai_conversation_service_v1.context_resolver import (
    AIConversationContextResolver,
)
from lib.services.patient_profile_service import PatientProfileService
from lib.services.qdrant_search_engine.qdrant_search_engine import (
    QdrantSearchEngine,
)


class AIConversationContextBuilder:
    def __init__(
        self,
        qdrant_search_engine: QdrantSearchEngine,
        patient_profile_service: PatientProfileService,
        ai_messages_collection: MongoStore,
        context_resolver: AIConversationContextResolver,
    ):
        self.qdrant_search_engine = qdrant_search_engine
        self.patient_profile_service = patient_profile_service
        self.ai_messages_collection = ai_messages_collection
        self.context_resolver = context_resolver

    async def build_context(
        self,
        patient_ids: list[str],
        conversation_id: str,
        human_input: str,
        include_history: bool = True,
    ) -> Dict[str, Any]:
        # Search vector DB
        qdrant_data = await self.qdrant_search_engine.search(
            human_input,
            100,
            patient_ids=patient_ids,
            conversation_id=conversation_id,
        )

        # Resolve missing profiles (cache or DB)
        resolved_context = await self.context_resolver.resolve_context(
            qdrant_results=qdrant_data["results"],
        )

        # Extract payloads only
        payload_items = [
            {**point.payload, "source": "qdrant"}
            for point in qdrant_data["results"]
        ]

        # Add missing profiles from DB/cache
        for pid, profile in resolved_context["profiles_added"].items():
            payload_items.append(
                {**profile, "data_type": "profile", "source": "db_cache"}
            )

        conversation_history = []

        if include_history:
            recent_messages = await self._get_recent_messages(
                conversation_id, limit=10
            )
            # summary = await self._get_conversation_summary(conversation_id)

            conversation_history = {
                # "summary": summary,
                "recent": recent_messages,
            }

        return {
            "context_items": payload_items,
            "conversation": conversation_history,
            "filter_applied": qdrant_data["filter_applied"],
        }

    async def _get_recent_messages(
        self, conversation_id: str, limit: int = 10
    ):
        filters: Any = {"conversation_id": conversation_id}
        pipeline = [
            {"$match": filters},
            {"$sort": {"timestamp": -1}},
            {"$limit": limit},
            {"$sort": {"timestamp": 1}},
            {"$addFields": {"_id": {"$toString": "$_id"}}},
        ]

        messages = await self.ai_messages_collection.aggregate(pipeline).to_list(length=limit)  # type: ignore
        return messages
