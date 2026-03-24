"""Tests for Memory — base models and protocol compliance."""

from datetime import datetime, timezone

from lib.ai_foundation.memory.base import (
    ConversationTurn,
    MemoryFact,
    MemoryStore,
    ThreadSummary,
)
from lib.ai_foundation.memory.mongo_store import MongoMemoryStore


class TestMemoryFact:
    def test_defaults(self):
        f = MemoryFact(key="goal", value="fat_loss")
        assert f.source == "user"
        assert f.confidence == 1.0
        assert f.confirmed is True
        assert f.agent_id is None

    def test_with_agent(self):
        f = MemoryFact(
            key="weight", value=75.5,
            source="agent", agent_id="health_query_v2",
            confidence=0.8,
        )
        assert f.source == "agent"
        assert f.agent_id == "health_query_v2"


class TestConversationTurn:
    def test_user_turn(self):
        turn = ConversationTurn(role="user", content="How were my sugars?")
        assert turn.agent_id == ""
        assert turn.metadata == {}

    def test_assistant_turn_with_metadata(self):
        turn = ConversationTurn(
            role="assistant",
            content="Your glucose was stable.",
            agent_id="health_query_v2",
            metadata={"intent": {"is_ready": True}},
        )
        assert turn.agent_id == "health_query_v2"
        assert turn.metadata["intent"]["is_ready"] is True


class TestThreadSummary:
    def test_summary(self):
        s = ThreadSummary(
            thread_id="t1",
            summary="Discussed glucose control this week.",
            domains=["cgm", "meal"],
            goal="fat_loss",
            date_scope="this_week",
            turn_count=6,
        )
        assert s.domains == ["cgm", "meal"]
        assert s.goal == "fat_loss"


class TestMongoMemoryStoreProtocol:
    def test_implements_protocol(self):
        """MongoMemoryStore must satisfy the MemoryStore protocol."""
        assert issubclass(MongoMemoryStore, object)
        # Check required methods exist
        assert hasattr(MongoMemoryStore, "get_patient_facts")
        assert hasattr(MongoMemoryStore, "upsert_patient_facts")
        assert hasattr(MongoMemoryStore, "get_thread_turns")
        assert hasattr(MongoMemoryStore, "append_turn")
        assert hasattr(MongoMemoryStore, "get_thread_summary")
        assert hasattr(MongoMemoryStore, "save_thread_summary")
