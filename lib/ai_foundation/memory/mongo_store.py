"""
MongoDB Memory Store — production implementation of the MemoryStore protocol.

Stores patient memories, conversation turns, and thread summaries in MongoDB.
Uses upsert semantics for memories (newer/higher-confidence wins).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pymongo import ReplaceOne

from lib.ai_foundation.config import settings
from .base import SOURCE_PRIORITY, ConversationTurn, MemoryFact, MemorySource, ThreadSummary

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
            summaries.create_index("updated_at", name="summaries_ttl_idx", expireAfterSeconds=settings.SUMMARIES_TTL_DAYS * 24 * 3600),
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

        # Safety cap: compaction keeps counts ~50, so 500 means it's broken.
        # Sorted by updated_at desc, truncation drops the OLDEST facts —
        # deliberate degradation, callers always see the freshest memories.
        docs = await cursor.to_list(length=500)
        if len(docs) == 500:
            logger.warning(
                "Patient %s hit the 500-memory read cap (oldest dropped) — compaction is not keeping up",
                patient_id[:8],
            )
        return [MemoryFact(**doc) for doc in docs]

    async def upsert_patient_facts(
        self, patient_id: str, facts: list[MemoryFact]
    ) -> None:
        """Merge memories into the patient's store.

        Precedence is SOURCE-first: an auto-extracted fact can never
        overwrite a user-explicit one (the patient's word beats the LLM's
        inference), regardless of recency. Within the same source tier,
        newer or higher-confidence wins.

        Efficiency: one indexed read for all keys + one bulk_write —
        not a find_one/write pair per fact.
        """
        if not facts:
            return
        collection = self._mongo.get_collection(FACTS_COLLECTION)

        by_key: dict[str, MemoryFact] = {}
        for fact in facts:
            by_key[_normalize_key(fact.key)] = fact

        existing_docs = {
            doc["key"]: doc
            async for doc in collection.find(
                {"patient_id": patient_id, "key": {"$in": list(by_key)}},
                {"_id": 0, "key": 1, "confidence": 1, "updated_at": 1,
                 "source": 1, "created_at": 1},
            )
        }

        ops: list[ReplaceOne] = []
        for key, fact in by_key.items():
            doc = fact.model_dump(mode="json")
            doc["key"] = key
            doc["patient_id"] = patient_id

            existing = existing_docs.get(key)
            if existing is None:
                doc["created_at"] = doc.get("created_at") or doc["updated_at"]
                # upsert=True makes the insert race-safe: a concurrent
                # writer's insert turns ours into a replace, no E11000.
                ops.append(ReplaceOne(
                    {"patient_id": patient_id, "key": key}, doc, upsert=True,
                ))
                continue

            if not self._should_replace(fact, existing):
                logger.debug(
                    "Memory kept (existing wins): %s.%s [%s does not beat %s]",
                    patient_id, key, fact.source, existing.get("source"),
                )
                continue

            # Preserve first-seen time across the full-document replace
            doc["created_at"] = (
                existing.get("created_at") or existing.get("updated_at")
                or doc["updated_at"]
            )
            ops.append(ReplaceOne(
                {"patient_id": patient_id, "key": key}, doc, upsert=True,
            ))
            logger.debug("Updated memory: %s.%s = %s", patient_id, key, fact.value)

        if ops:
            await collection.bulk_write(ops, ordered=False)

    @staticmethod
    def _should_replace(fact: MemoryFact, existing: dict) -> bool:
        """Source tier first, then recency/confidence within the tier."""
        new_priority = SOURCE_PRIORITY.get(fact.source, 0)
        old_priority = SOURCE_PRIORITY.get(
            existing.get("source", MemorySource.AUTO_EXTRACTED.value), 0,
        )
        if new_priority != old_priority:
            return new_priority > old_priority

        existing_time = existing.get("updated_at")
        if isinstance(existing_time, str):
            existing_time = datetime.fromisoformat(existing_time)
        if existing_time and existing_time.tzinfo is None:
            existing_time = existing_time.replace(tzinfo=timezone.utc)
        new_time = fact.updated_at
        if new_time.tzinfo is None:
            new_time = new_time.replace(tzinfo=timezone.utc)

        return (
            fact.confidence > existing.get("confidence", 0)
            or new_time > (existing_time or datetime.min.replace(tzinfo=timezone.utc))
        )

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

    @staticmethod
    def _turn_doc(thread_id: str, turn: ConversationTurn) -> dict:
        doc = turn.model_dump(mode="json")
        doc["thread_id"] = thread_id
        # Real BSON date, not the json-dump ISO string: Mongo TTL indexes
        # only expire Date-typed fields, so the 90-day retention depends on
        # this. (scripts/migrate_memory_timestamps.py converts legacy
        # string-typed docs.)
        doc["timestamp"] = turn.timestamp
        return doc

    async def append_turn(
        self, thread_id: str, turn: ConversationTurn
    ) -> None:
        """Append a turn to a conversation thread."""
        collection = self._mongo.get_collection(TURNS_COLLECTION)
        await collection.insert_one(self._turn_doc(thread_id, turn))

    async def append_turns_batch(
        self, thread_id: str, turns: list[ConversationTurn]
    ) -> list:
        """Append multiple turns in a single batch write.

        Returns the inserted Mongo ids (same order as ``turns``) so callers
        can target a specific turn later — e.g. attaching the async English
        audit translation to exactly the turn it belongs to.
        """
        if not turns:
            return []
        collection = self._mongo.get_collection(TURNS_COLLECTION)
        docs = [self._turn_doc(thread_id, turn) for turn in turns]
        result = await collection.insert_many(docs)
        return list(result.inserted_ids)

    async def update_turn_metadata_by_id(
        self, turn_id: Any, metadata_patch: dict
    ) -> bool:
        """Merge keys into a specific turn's metadata (targeted by Mongo id —
        never "the latest turn", which races with fast follow-up messages)."""
        collection = self._mongo.get_collection(TURNS_COLLECTION)
        result = await collection.update_one(
            {"_id": turn_id},
            {"$set": {f"metadata.{k}": v for k, v in metadata_patch.items()}},
        )
        return result.matched_count > 0

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
        """Save or replace a thread summary.

        Whole-document write — use ONLY when constructing a brand-new summary.
        Concurrent writers that own individual fields must use
        :meth:`update_thread_summary_fields` or they clobber each other.
        """
        collection = self._mongo.get_collection(SUMMARIES_COLLECTION)
        doc = summary.model_dump(mode="json")
        doc["thread_id"] = thread_id
        doc["updated_at"] = datetime.now(timezone.utc)  # BSON date for TTL
        await collection.replace_one(
            {"thread_id": thread_id},
            doc,
            upsert=True,
        )

    async def update_thread_summary_fields(
        self, thread_id: str, fields: dict
    ) -> None:
        """Partial ``$set`` on a thread summary — each writer touches only
        the fields it owns, so the pending-request recorder, the open-question
        updater, compaction, and the event-scan consumer cannot wipe each
        other's state (they race on every reply)."""
        collection = self._mongo.get_collection(SUMMARIES_COLLECTION)
        set_fields = dict(fields)
        set_fields["updated_at"] = datetime.now(timezone.utc)  # BSON date for TTL
        defaults = {"thread_id": thread_id, "summary": "", "turn_count": 0}
        on_insert = {k: v for k, v in defaults.items() if k not in set_fields}
        await collection.update_one(
            {"thread_id": thread_id},
            {"$set": set_fields, "$setOnInsert": on_insert},
            upsert=True,
        )
