"""
MongoDB Memory Store — production implementation of the MemoryStore protocol.

Stores patient memories, conversation turns, and thread summaries in MongoDB.
Uses upsert semantics for memories (newer/higher-confidence wins).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from lib.ai_foundation.config import settings
from .base import ConversationTurn, MemoryFact, ThreadSummary

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore

logger = logging.getLogger(__name__)

# Collection names
FACTS_COLLECTION = "ai_patient_memory"
TURNS_COLLECTION = "ai_conversation_turns"
SUMMARIES_COLLECTION = "ai_thread_summaries"


def _normalize_key(key: str) -> str:
    """Normalize a memory key: lowercase, strip, spaces → underscores."""
    return key.strip().lower().replace(" ", "_").replace("-", "_")


class MongoMemoryStore:
    """MongoDB-backed implementation of the MemoryStore protocol.

    Indexes are created on first use via ``ensure_indexes()``.

    Example::

        store = MongoMemoryStore(mongo_store)
        await store.ensure_indexes()

        # Store a memory
        await store.upsert_patient_facts("p123", [
            MemoryFact(key="health_goal", value="fat loss", category="goal"),
        ])

        # Retrieve memories (from any agent)
        facts = await store.get_patient_facts("p123")
    """

    def __init__(self, mongo_store: MongoStore) -> None:
        self._mongo = mongo_store

    def get_collection(self, name: str):
        """Public accessor for MongoDB collections."""
        return self._mongo.get_collection(name)

    async def ensure_indexes(self) -> None:
        """Create MongoDB indexes for efficient queries and TTL cleanup. Idempotent."""
        import asyncio

        facts = self._mongo.get_collection(FACTS_COLLECTION)
        turns = self._mongo.get_collection(TURNS_COLLECTION)
        summaries = self._mongo.get_collection(SUMMARIES_COLLECTION)

        await asyncio.gather(
            facts.create_index([("patient_id", 1), ("key", 1)], name="patient_key_idx", unique=True),
            turns.create_index([("thread_id", 1), ("timestamp", 1)], name="thread_time_idx"),
            turns.create_index("timestamp", name="turns_ttl_idx", expireAfterSeconds=settings.TURNS_TTL_DAYS * 24 * 3600),
            summaries.create_index([("thread_id", 1)], name="thread_idx", unique=True),
            summaries.create_index("updated_at", name="summaries_ttl_idx", expireAfterSeconds=settings.TURNS_TTL_DAYS * 24 * 3600),
        )

        logger.debug("Memory store indexes ensured.")

    # -- Patient Memories ---------------------------------------------------

    async def get_patient_facts(self, patient_id: str) -> list[MemoryFact]:
        """Retrieve all known memories about a patient."""
        collection = self._mongo.get_collection(FACTS_COLLECTION)
        cursor = collection.find(
            {"patient_id": patient_id},
            {"_id": 0, "patient_id": 0},
        ).sort("updated_at", -1)

        docs = await cursor.to_list(length=100)
        return [MemoryFact(**doc) for doc in docs]

    async def upsert_patient_facts(
        self, patient_id: str, facts: list[MemoryFact]
    ) -> None:
        """Merge memories into the patient's store.

        For each memory:
        - Key is normalized (lowercase, underscores).
        - If the key doesn't exist → insert.
        - If the key exists and new memory is more recent or higher confidence → update.
        - Otherwise → skip (existing memory is better).
        """
        collection = self._mongo.get_collection(FACTS_COLLECTION)

        for fact in facts:
            normalized_key = _normalize_key(fact.key)
            doc = fact.model_dump(mode="json")
            doc["key"] = normalized_key
            doc["patient_id"] = patient_id

            existing = await collection.find_one(
                {"patient_id": patient_id, "key": normalized_key},
                {"_id": 0, "confidence": 1, "updated_at": 1},
            )

            if existing is None:
                await collection.insert_one(doc)
                logger.debug("New memory: %s.%s = %s", patient_id, normalized_key, fact.value)
            else:
                # Compare properly — handle both datetime objects and strings
                existing_time = existing.get("updated_at")
                new_time = fact.updated_at
                if isinstance(existing_time, str):
                    existing_time = datetime.fromisoformat(existing_time)
                if existing_time and existing_time.tzinfo is None:
                    existing_time = existing_time.replace(tzinfo=timezone.utc)
                if new_time.tzinfo is None:
                    new_time = new_time.replace(tzinfo=timezone.utc)

                should_update = (
                    fact.confidence > existing.get("confidence", 0)
                    or new_time > (existing_time or datetime.min.replace(tzinfo=timezone.utc))
                )
                if should_update:
                    await collection.replace_one(
                        {"patient_id": patient_id, "key": normalized_key},
                        doc,
                    )
                    logger.debug("Updated memory: %s.%s = %s", patient_id, normalized_key, fact.value)

    async def delete_patient_fact(self, patient_id: str, key: str) -> bool:
        """Delete a specific memory by key. Returns True if deleted."""
        collection = self._mongo.get_collection(FACTS_COLLECTION)
        normalized_key = _normalize_key(key)
        result = await collection.delete_one(
            {"patient_id": patient_id, "key": normalized_key},
        )
        if result.deleted_count > 0:
            logger.debug("Deleted memory: %s.%s", patient_id, normalized_key)
            return True
        return False

    async def delete_patient_facts(self, patient_id: str, keys: list[str]) -> int:
        """Delete multiple memories by keys. Returns number of deleted records."""
        if not keys:
            return 0

        collection = self._mongo.get_collection(FACTS_COLLECTION)
        normalized_keys = list({_normalize_key(k) for k in keys if k})
        if not normalized_keys:
            return 0

        result = await collection.delete_many(
            {"patient_id": patient_id, "key": {"$in": normalized_keys}},
        )
        deleted = result.deleted_count or 0
        if deleted > 0:
            logger.debug(
                "Deleted %d memories for %s (keys=%d)",
                deleted,
                patient_id,
                len(normalized_keys),
            )
        return deleted

    # -- Conversation Turns -------------------------------------------------

    async def count_thread_turns(self, thread_id: str) -> int:
        """Count total turns in a thread without loading them."""
        collection = self._mongo.get_collection(TURNS_COLLECTION)
        return await collection.count_documents({"thread_id": thread_id})

    async def get_first_thread_turns(self, thread_id: str, *, limit: int = 2) -> list[ConversationTurn]:
        """Retrieve the earliest turns from a thread (for title generation)."""
        collection = self._mongo.get_collection(TURNS_COLLECTION)
        cursor = (
            collection.find(
                {"thread_id": thread_id},
                {"_id": 0, "thread_id": 0},
            )
            .sort("timestamp", 1)
            .limit(limit)
        )
        docs = await cursor.to_list(length=limit)
        return [ConversationTurn(**doc) for doc in docs]

    async def get_thread_turns(
        self, thread_id: str, *, limit: int = 20
    ) -> list[ConversationTurn]:
        """Retrieve recent turns from a conversation thread (newest last)."""
        collection = self._mongo.get_collection(TURNS_COLLECTION)

        # Get the last N turns, sorted ascending (oldest first)
        cursor = (
            collection.find(
                {"thread_id": thread_id},
                {"_id": 0, "thread_id": 0},
            )
            .sort("timestamp", -1)
            .limit(limit)
        )
        docs = await cursor.to_list(length=limit)
        docs.reverse()  # chronological order
        return [ConversationTurn(**doc) for doc in docs]

    async def append_turn(
        self, thread_id: str, turn: ConversationTurn
    ) -> None:
        """Append a turn to a conversation thread."""
        collection = self._mongo.get_collection(TURNS_COLLECTION)
        doc = turn.model_dump(mode="json")
        doc["thread_id"] = thread_id
        await collection.insert_one(doc)

    async def append_turns_batch(
        self, thread_id: str, turns: list[ConversationTurn]
    ) -> None:
        """Append multiple turns in a single batch write."""
        if not turns:
            return
        collection = self._mongo.get_collection(TURNS_COLLECTION)
        docs = []
        for turn in turns:
            doc = turn.model_dump(mode="json")
            doc["thread_id"] = thread_id
            docs.append(doc)
        await collection.insert_many(docs)

    # -- Thread Summaries ---------------------------------------------------

    async def get_thread_summary(self, thread_id: str) -> ThreadSummary | None:
        """Retrieve the latest compacted summary for a thread."""
        collection = self._mongo.get_collection(SUMMARIES_COLLECTION)
        doc = await collection.find_one(
            {"thread_id": thread_id},
            {"_id": 0},
        )
        return ThreadSummary(**doc) if doc else None

    async def save_thread_summary(
        self, thread_id: str, summary: ThreadSummary
    ) -> None:
        """Save or replace a thread summary."""
        collection = self._mongo.get_collection(SUMMARIES_COLLECTION)
        doc = summary.model_dump(mode="json")
        doc["thread_id"] = thread_id
        await collection.replace_one(
            {"thread_id": thread_id},
            doc,
            upsert=True,
        )
