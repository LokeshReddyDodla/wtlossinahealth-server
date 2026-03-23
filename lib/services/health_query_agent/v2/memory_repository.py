from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable, Optional

from lib.core.mongo_store import MongoStore

from .models import (
    AnalysisSnapshot,
    ConversationCompaction,
    PatientMemoryFact,
    ThreadState,
)


class HealthAgentMemoryRepository:
    PATIENT_MEMORY_COLLECTION = "patient_agent_memory"
    THREAD_STATE_COLLECTION = "thread_agent_state"
    ANALYSIS_SNAPSHOT_COLLECTION = "analysis_snapshots"
    CONVERSATION_COMPACTION_COLLECTION = "conversation_compactions"

    def __init__(self, mongo_store: Optional[MongoStore] = None):
        self.mongo_store = mongo_store
        self._indexes_initialized = False

    async def ensure_indexes(self) -> None:
        if not self.mongo_store or self._indexes_initialized:
            return

        await self.mongo_store.get_collection(
            self.PATIENT_MEMORY_COLLECTION
        ).create_index(
            [("patient_id", 1)],
            name="patient_agent_memory_patient_id_idx",
            unique=True,
            background=True,
        )
        await self.mongo_store.get_collection(
            self.THREAD_STATE_COLLECTION
        ).create_index(
            [("thread_id", 1)],
            name="thread_agent_state_thread_id_idx",
            unique=True,
            background=True,
        )
        await self.mongo_store.get_collection(
            self.THREAD_STATE_COLLECTION
        ).create_index(
            [("patient_id", 1), ("updated_at", -1)],
            name="thread_agent_state_patient_updated_idx",
            background=True,
            sparse=True,
        )
        await self.mongo_store.get_collection(
            self.ANALYSIS_SNAPSHOT_COLLECTION
        ).create_index(
            [("patient_id", 1), ("generated_at", -1)],
            name="analysis_snapshots_patient_generated_idx",
            background=True,
            sparse=True,
        )
        await self.mongo_store.get_collection(
            self.ANALYSIS_SNAPSHOT_COLLECTION
        ).create_index(
            [("thread_id", 1), ("generated_at", -1)],
            name="analysis_snapshots_thread_generated_idx",
            background=True,
            sparse=True,
        )
        await self.mongo_store.get_collection(
            self.CONVERSATION_COMPACTION_COLLECTION
        ).create_index(
            [("thread_id", 1), ("created_at", -1)],
            name="conversation_compactions_thread_created_idx",
            background=True,
        )
        await self.mongo_store.get_collection(
            self.CONVERSATION_COMPACTION_COLLECTION
        ).create_index(
            [("patient_id", 1), ("created_at", -1)],
            name="conversation_compactions_patient_created_idx",
            background=True,
            sparse=True,
        )
        self._indexes_initialized = True

    async def get_patient_memory(self, patient_id: Optional[str]) -> list[PatientMemoryFact]:
        if not self.mongo_store or not patient_id:
            return []
        doc = await self.mongo_store.find_document(
            self.PATIENT_MEMORY_COLLECTION,
            {"patient_id": patient_id},
        )
        if not doc:
            return []
        return [PatientMemoryFact(**fact) for fact in doc.get("facts", [])]

    async def upsert_patient_facts(
        self,
        patient_id: Optional[str],
        facts: Iterable[PatientMemoryFact],
    ) -> None:
        if not self.mongo_store or not patient_id:
            return
        existing = await self.get_patient_memory(patient_id)
        merged: dict[str, PatientMemoryFact] = {fact.key: fact for fact in existing}
        for fact in facts:
            current = merged.get(fact.key)
            if current is None or fact.confirmed or fact.confidence >= current.confidence:
                merged[fact.key] = fact
        payload = {
            "patient_id": patient_id,
            "facts": [fact.model_dump(mode="json") for fact in merged.values()],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        existing_doc = await self.mongo_store.find_document(
            self.PATIENT_MEMORY_COLLECTION,
            {"patient_id": patient_id},
        )
        if existing_doc:
            await self.mongo_store.update_document(
                self.PATIENT_MEMORY_COLLECTION,
                {"patient_id": patient_id},
                payload,
            )
        else:
            await self.mongo_store.insert_document(
                self.PATIENT_MEMORY_COLLECTION,
                payload,
            )

    async def get_thread_state(self, thread_id: str) -> Optional[ThreadState]:
        if not self.mongo_store:
            return None
        doc = await self.mongo_store.find_document(
            self.THREAD_STATE_COLLECTION,
            {"thread_id": thread_id},
        )
        if not doc:
            return None
        doc.pop("_id", None)
        return ThreadState(**doc)

    async def upsert_thread_state(self, state: ThreadState) -> None:
        if not self.mongo_store:
            return
        payload = state.model_dump(mode="json")
        modified = await self.mongo_store.update_document(
            self.THREAD_STATE_COLLECTION,
            {"thread_id": state.thread_id},
            payload,
        )
        if not modified:
            await self.mongo_store.insert_document(self.THREAD_STATE_COLLECTION, payload)

    async def save_analysis_snapshot(self, snapshot: AnalysisSnapshot) -> None:
        if not self.mongo_store:
            return
        await self.mongo_store.insert_document(
            self.ANALYSIS_SNAPSHOT_COLLECTION,
            snapshot.model_dump(mode="json"),
        )

    async def save_conversation_compaction(
        self, compaction: ConversationCompaction
    ) -> None:
        if not self.mongo_store:
            return
        await self.mongo_store.insert_document(
            self.CONVERSATION_COMPACTION_COLLECTION,
            compaction.model_dump(mode="json"),
        )

    async def get_latest_conversation_compaction(
        self, thread_id: str
    ) -> Optional[ConversationCompaction]:
        if not self.mongo_store:
            return None
        collection = self.mongo_store.get_collection(
            self.CONVERSATION_COMPACTION_COLLECTION
        )
        doc = await collection.find_one(
            {"thread_id": thread_id},
            sort=[("created_at", -1)],
        )
        if not doc:
            return None
        doc.pop("_id", None)
        return ConversationCompaction(**doc)

    async def get_thread_runtime_state(
        self, thread_id: str
    ) -> tuple[Optional[ThreadState], Optional[ConversationCompaction]]:
        thread_state = await self.get_thread_state(thread_id)
        latest_compaction = await self.get_latest_conversation_compaction(thread_id)
        return thread_state, latest_compaction

    @staticmethod
    def summarize_patient_memory(facts: Iterable[PatientMemoryFact]) -> str:
        lines = []
        for fact in facts:
            lines.append(f"- {fact.key}: {fact.value}")
        return "\n".join(lines)
