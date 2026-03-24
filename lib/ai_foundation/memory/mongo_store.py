"""
MongoDB Memory Store — production implementation of the MemoryStore protocol.

Stores patient facts, conversation turns, and thread summaries in MongoDB.
Uses upsert semantics for facts (newer/higher-confidence wins).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .base import ConversationTurn, MemoryFact, ThreadSummary

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore

logger = logging.getLogger(__name__)

# Collection names
FACTS_COLLECTION = "ai_patient_memory"
TURNS_COLLECTION = "ai_conversation_turns"
SUMMARIES_COLLECTION = "ai_thread_summaries"


class MongoMemoryStore:
    """MongoDB-backed implementation of the MemoryStore protocol.

    Indexes are created on first use via ``ensure_indexes()``.

    Example::

        store = MongoMemoryStore(mongo_store)
        await store.ensure_indexes()

        # Store a fact
        await store.upsert_patient_facts("p123", [
            MemoryFact(key="goal", value="fat_loss", source="user", agent_id="health_query_v2"),
        ])

        # Retrieve facts (from any agent)
        facts = await store.get_patient_facts("p123")
    """

    def __init__(self, mongo_store: MongoStore) -> None:
        self._mongo = mongo_store

    async def ensure_indexes(self) -> None:
        """Create MongoDB indexes for efficient queries. Idempotent."""
        facts = self._mongo.get_collection(FACTS_COLLECTION)
        await facts.create_index(
            [("patient_id", 1), ("key", 1)],
            name="patient_key_idx",
            unique=True,
        )

        turns = self._mongo.get_collection(TURNS_COLLECTION)
        await turns.create_index(
            [("thread_id", 1), ("timestamp", 1)],
            name="thread_time_idx",
        )

        summaries = self._mongo.get_collection(SUMMARIES_COLLECTION)
        await summaries.create_index(
            [("thread_id", 1)],
            name="thread_idx",
            unique=True,
        )

        logger.debug("Memory store indexes ensured.")

    # -- Patient Facts ------------------------------------------------------

    async def get_patient_facts(self, patient_id: str) -> list[MemoryFact]:
        """Retrieve all known facts about a patient."""
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
        """Merge facts into the patient's fact store.

        For each fact:
        - If the key doesn't exist → insert.
        - If the key exists and new fact is more recent or higher confidence → update.
        - Otherwise → skip (existing fact is better).
        """
        collection = self._mongo.get_collection(FACTS_COLLECTION)

        for fact in facts:
            doc = fact.model_dump(mode="json")
            doc["patient_id"] = patient_id

            # Upsert: update only if new fact is more recent or higher confidence
            existing = await collection.find_one(
                {"patient_id": patient_id, "key": fact.key},
                {"_id": 0, "confidence": 1, "updated_at": 1},
            )

            if existing is None:
                await collection.insert_one(doc)
                logger.debug("New fact: %s.%s = %s", patient_id, fact.key, fact.value)
            else:
                should_update = (
                    fact.confidence > existing.get("confidence", 0)
                    or fact.updated_at.isoformat() > str(existing.get("updated_at", ""))
                )
                if should_update:
                    await collection.replace_one(
                        {"patient_id": patient_id, "key": fact.key},
                        doc,
                    )
                    logger.debug("Updated fact: %s.%s = %s", patient_id, fact.key, fact.value)

    # -- Conversation Turns -------------------------------------------------

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
