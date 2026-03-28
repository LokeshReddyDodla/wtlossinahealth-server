"""Tests for Memory — models, protocol, and key normalization."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.memory.base import (
    ConversationTurn,
    MemoryCategory,
    MemoryFact,
    MemorySource,
    MemoryStore,
    ThreadSummary,
)
from lib.ai_foundation.memory.mongo_store import MongoMemoryStore, _normalize_key


# ---------------------------------------------------------------------------
# MemoryFact model
# ---------------------------------------------------------------------------


class TestMemoryFact:
    def test_defaults(self):
        f = MemoryFact(key="goal", value="fat_loss")
        assert f.source == MemorySource.AUTO_EXTRACTED.value
        assert f.category == MemoryCategory.OTHER.value
        assert f.confidence == 1.0
        assert f.is_permanent is False
        assert f.agent_id is None

    def test_user_explicit(self):
        f = MemoryFact(
            key="dietary_preference", value="vegetarian",
            source=MemorySource.USER_EXPLICIT.value,
            category=MemoryCategory.PREFERENCE.value,
            confidence=1.0,
        )
        assert f.source == "user_explicit"
        assert f.category == "preference"

    def test_with_agent(self):
        f = MemoryFact(
            key="weight", value="75 kg",
            agent_id="health_query_v3",
            category="health",
            confidence=0.9,
        )
        assert f.agent_id == "health_query_v3"

    def test_permanent(self):
        f = MemoryFact(
            key="food_allergy", value="peanuts",
            is_permanent=True,
            category="condition",
        )
        assert f.is_permanent is True

    def test_backward_compat_old_doc(self):
        """Old MongoDB documents without category/source/is_permanent should still parse."""
        old_doc = {
            "key": "goal",
            "value": "fat loss",
            "confidence": 1.0,
            "updated_at": "2026-03-20T10:00:00",
        }
        f = MemoryFact(**old_doc)
        assert f.category == "other"  # default
        assert f.source == "auto_extracted"  # default
        assert f.is_permanent is False  # default


# ---------------------------------------------------------------------------
# Key normalization
# ---------------------------------------------------------------------------


class TestKeyNormalization:
    def test_lowercase(self):
        assert _normalize_key("DIETARY_PREFERENCE") == "dietary_preference"

    def test_spaces_to_underscores(self):
        assert _normalize_key("health goal") == "health_goal"

    def test_dashes_to_underscores(self):
        assert _normalize_key("food-allergy") == "food_allergy"

    def test_strip(self):
        assert _normalize_key("  weight  ") == "weight"

    def test_mixed(self):
        assert _normalize_key("  Health Goal  ") == "health_goal"

    def test_already_normalized(self):
        assert _normalize_key("dietary_preference") == "dietary_preference"


# ---------------------------------------------------------------------------
# ConversationTurn
# ---------------------------------------------------------------------------


class TestConversationTurn:
    def test_user_turn(self):
        turn = ConversationTurn(role="user", content="How were my sugars?")
        assert turn.agent_id == ""
        assert turn.metadata == {}

    def test_assistant_turn_with_metadata(self):
        turn = ConversationTurn(
            role="assistant",
            content="Your glucose was stable.",
            agent_id="health_query_v3",
            metadata={"tier": "standard", "rounds_used": 2},
        )
        assert turn.agent_id == "health_query_v3"
        assert turn.metadata["tier"] == "standard"


# ---------------------------------------------------------------------------
# ThreadSummary
# ---------------------------------------------------------------------------


class TestThreadSummary:
    def test_summary(self):
        s = ThreadSummary(
            thread_id="t1",
            summary="Discussed glucose control this week.",
            domains=["cgm", "meal"],
            goal="fat_loss",
            turn_count=6,
        )
        assert s.domains == ["cgm", "meal"]
        assert s.goal == "fat_loss"

    def test_with_patient_ids(self):
        s = ThreadSummary(
            thread_id="t1", summary="test",
            patient_ids=["p1", "p2"],
        )
        assert s.patient_ids == ["p1", "p2"]


# ---------------------------------------------------------------------------
# MongoMemoryStore protocol compliance
# ---------------------------------------------------------------------------


class TestMongoMemoryStoreProtocol:
    def test_has_required_methods(self):
        assert hasattr(MongoMemoryStore, "get_patient_facts")
        assert hasattr(MongoMemoryStore, "upsert_patient_facts")
        assert hasattr(MongoMemoryStore, "delete_patient_fact")
        assert hasattr(MongoMemoryStore, "get_thread_turns")
        assert hasattr(MongoMemoryStore, "append_turn")
        assert hasattr(MongoMemoryStore, "get_thread_summary")
        assert hasattr(MongoMemoryStore, "save_thread_summary")


# ---------------------------------------------------------------------------
# MongoMemoryStore with mocked MongoDB
# ---------------------------------------------------------------------------


def _make_mock_store():
    mongo = MagicMock()
    collection = AsyncMock()
    collection.find_one = AsyncMock(return_value=None)
    collection.insert_one = AsyncMock()
    collection.replace_one = AsyncMock()
    collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    collection.create_index = AsyncMock()

    cursor = AsyncMock()
    cursor.to_list = AsyncMock(return_value=[])
    cursor.sort = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)
    collection.find = MagicMock(return_value=cursor)

    mongo.get_collection = MagicMock(return_value=collection)
    return MongoMemoryStore(mongo), collection


class TestMongoMemoryStoreUpsert:
    @pytest.mark.asyncio
    async def test_insert_new_fact(self):
        store, collection = _make_mock_store()
        collection.find_one = AsyncMock(return_value=None)

        fact = MemoryFact(key="Health Goal", value="fat loss", category="goal")
        await store.upsert_patient_facts("p1", [fact])

        collection.insert_one.assert_called_once()
        doc = collection.insert_one.call_args[0][0]
        assert doc["key"] == "health_goal"  # normalized
        assert doc["patient_id"] == "p1"
        assert doc["category"] == "goal"

    @pytest.mark.asyncio
    async def test_update_existing_fact(self):
        store, collection = _make_mock_store()
        collection.find_one = AsyncMock(return_value={
            "confidence": 0.5,
            "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        })

        fact = MemoryFact(key="weight", value="80 kg", confidence=0.9)
        await store.upsert_patient_facts("p1", [fact])

        collection.replace_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_when_existing_is_better(self):
        store, collection = _make_mock_store()
        collection.find_one = AsyncMock(return_value={
            "confidence": 1.0,
            "updated_at": datetime(2099, 1, 1, tzinfo=timezone.utc),  # future
        })

        fact = MemoryFact(key="weight", value="80 kg", confidence=0.5)
        await store.upsert_patient_facts("p1", [fact])

        collection.replace_one.assert_not_called()
        collection.insert_one.assert_not_called()


class TestMongoMemoryStoreDelete:
    @pytest.mark.asyncio
    async def test_delete_existing(self):
        store, collection = _make_mock_store()
        collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        result = await store.delete_patient_fact("p1", "Health Goal")
        assert result is True
        collection.delete_one.assert_called_once_with(
            {"patient_id": "p1", "key": "health_goal"},  # normalized
        )

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        store, collection = _make_mock_store()
        collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))

        result = await store.delete_patient_fact("p1", "nonexistent")
        assert result is False


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_memory_category_values(self):
        assert MemoryCategory.CONDITION.value == "condition"
        assert MemoryCategory.GOAL.value == "goal"
        assert MemoryCategory.PREFERENCE.value == "preference"
        assert MemoryCategory.HEALTH.value == "health"
        assert MemoryCategory.LIFESTYLE.value == "lifestyle"
        assert MemoryCategory.OTHER.value == "other"

    def test_memory_source_values(self):
        assert MemorySource.USER_EXPLICIT.value == "user_explicit"
        assert MemorySource.AUTO_EXTRACTED.value == "auto_extracted"
        assert MemorySource.SYSTEM.value == "system"
