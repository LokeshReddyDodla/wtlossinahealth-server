from typing import List, Optional
from lib.core.cache_store import CacheStore
from lib.services.qdrant_search_engine.models import SearchIntent


class IntentCache(CacheStore):
    def __init__(
        self,
        intent_cache_store: CacheStore,
        ttl_seconds: int = 7200,
        max_length: int = 5,
    ):
        self.intent_cache_store = intent_cache_store
        self.ttl_seconds = ttl_seconds
        self.max_length = max_length

    def _build_key(self, conversation_id: str) -> str:
        return f"{conversation_id}"

    def get_recent_intents(
        self,
        conversation_id: str,
        limit: int = 3,
    ) -> List[SearchIntent]:
        key = self._build_key(conversation_id)

        full_key = f"{self.intent_cache_store._get_namespace()}_{key}"
        client = self.intent_cache_store._get_client()

        items = client.lrange(full_key, 0, limit - 1)

        if not items:
            return []
        return [SearchIntent.model_validate_json(i) for i in items]

    def push_intent(
        self,
        conversation_id: str,
        intent: SearchIntent,
        expire: Optional[int] = None,
    ) -> bool:
        key = self._build_key(conversation_id)
        serialized = intent.model_dump_json()
        ttl = expire or self.ttl_seconds

        client = self.intent_cache_store._get_client()
        full_key = f"{self.intent_cache_store._get_namespace()}_{key}"

        # Use pipeline for atomic operations
        pipeline = client.pipeline()
        pipeline.lpush(full_key, serialized)
        pipeline.ltrim(full_key, 0, self.max_length - 1)
        pipeline.expire(full_key, ttl)
        pipeline.execute()

        return True

    def clear_intents(self, conversation_id: str) -> bool:
        key = self._build_key(conversation_id)
        return bool(self.intent_cache_store.delete_key(key))
