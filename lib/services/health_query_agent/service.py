"""
Agent service for processing user queries and managing conversations.
"""

import logging
from datetime import UTC, datetime
from typing import Optional, Union

from fastapi import status

from lib.core.cache_store import CacheStore
from lib.core.constants import ProfileTypeEnum
from lib.core.mongo_store import MongoStore
from lib.core.qdrant_store import QdrantStore
from lib.services.health_query_agent.serialization import to_checkpoint_safe
from lib.utils.http_exceptions import raise_http_exception
from .conversation_repository import ConversationRepository
from .state_constants import RESET
from .v2 import (
    AnalysisSnapshot,
    ConversationMessage,
    ConversationCompaction,
    ConversationResolver,
    DomainName,
    HealthAgentMemoryRepository,
    QueryResponse,
    ResponseMode,
    ThreadState,
)
from .v2.compaction import build_conversation_compaction
from .workflow import build_workflow

logger = logging.getLogger(__name__)


class HealthQueryAgentService:
    def __init__(
        self,
        qdrant_store: QdrantStore,
        mongo_store: Optional[MongoStore] = None,
        cache_store: Optional[CacheStore] = None,
        app=None,
    ):
        self.qdrant_store = qdrant_store
        self.mongo_store = mongo_store
        self._indexes_initialized = False
        self.conversation_repository = (
            ConversationRepository(mongo_store) if mongo_store else None
        )
        self.memory_repository = HealthAgentMemoryRepository(mongo_store)
        self.app = app or build_workflow(
            qdrant_store,
            mongo_store=mongo_store,
            cache_store=cache_store,
        )

    async def _ensure_storage_indexes(self) -> None:
        if self._indexes_initialized:
            return

        if self.conversation_repository:
            await self.conversation_repository.ensure_indexes()
        await self.memory_repository.ensure_indexes()
        self._indexes_initialized = True

    async def _save_user_message(self, user_id: str, user_message: str, thread_id: str):
        if not self.conversation_repository or not user_id:
            return

        await self.conversation_repository.save_message(
            user_id=user_id,
            message_type="user",
            content=user_message,
            metadata={
                "thread_id": thread_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    async def _save_assistant_message(
        self,
        user_id: str,
        thread_id: str,
        intent,
        response_data: dict,
        is_ready: bool,
        source_messages: Optional[list] = None,
        retrieval_metadata: Optional[dict] = None,
    ):
        if not self.conversation_repository or not user_id:
            return

        intent_dict = to_checkpoint_safe(intent)

        response_dict = None
        if is_ready:
            response_dict = {
                "message": response_data["message"],
                "is_ready": response_data["is_ready"],
                "data_types": response_data["data_types"],
            }
            intent_dict.pop("clarification_msg", None)
        else:
            intent_dict["clarification_msg"] = getattr(
                intent, "clarification_msg", None
            )

        metadata = {
            "thread_id": thread_id,
            "turn_number": response_data.get("turn_number", 0),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if source_messages:
            metadata["source_messages"] = source_messages
        if retrieval_metadata:
            metadata["retrieval"] = retrieval_metadata

        await self.conversation_repository.save_message(
            user_id=user_id,
            message_type="assistant",
            content=response_data["message"],
            intent=intent_dict,
            response=response_dict,
            metadata=metadata,
        )

    def _get_conversation_messages(self, thread_id: str) -> list:
        config = {"configurable": {"thread_id": thread_id}}
        try:
            state = self.app.get_state(config)
            messages = state.values.get("messages") if state and state.values else []
            return messages.copy() if messages else []
        except Exception as e:
            logger.debug(f"Error getting state for thread_id {thread_id}: {e}")
        return []

    def _build_response_data(
        self, result: dict, user_message: str, intent, thread_id: str
    ) -> dict:
        config = {"configurable": {"thread_id": thread_id}}
        state = self.app.get_state(config)
        messages = state.values.get("messages", []) if state and state.values else []
        turn_number = sum(1 for m in messages if m.get("role") == "user")

        response_data = {
            "type": "response",
            "user_message": user_message,
            "message_count": len(messages),
            "turn_number": turn_number,
            "is_ready": getattr(intent, "is_ready", False) if intent else False,
            "message": "No intent determined" if not intent else "",
        }

        if intent:
            intent_dict = to_checkpoint_safe(intent)
            response_data.update(intent_dict)
            response_data["confidence"] = getattr(intent, "confidence", None)
            if result.get("executed_tools") is not None:
                response_data["executed_tools"] = result.get("executed_tools")
            if result.get("retrieval_metrics") is not None:
                response_data["retrieval_metrics"] = result.get("retrieval_metrics")

            if intent.is_ready:
                final_response = result.get(
                    "final_response", "Query executed successfully"
                )
                response_data["message"] = final_response
                response_data["final_response"] = final_response
                response_data["search_confidence"] = result.get("search_confidence")
            else:
                clarification = intent_dict.get(
                    "clarification_msg", "I need more information."
                )
                response_data["message"] = clarification
                response_data["clarification_msg"] = clarification
                response_data["suggestions"] = intent_dict.get("suggestions", [])

        return response_data

    def _resolve_memory_subject_id(
        self,
        user_id: Optional[str],
        user_role: Optional[str],
        patient_ids: Optional[list[str]],
    ) -> Optional[str]:
        if patient_ids and len(patient_ids) == 1:
            return patient_ids[0]
        return user_id if user_role == ProfileTypeEnum.PATIENT.value else None

    async def _get_runtime_thread_state(self, thread_id: str):
        if hasattr(self.memory_repository, "get_thread_runtime_state"):
            return await self.memory_repository.get_thread_runtime_state(thread_id)

        thread_state = None
        if hasattr(self.memory_repository, "get_thread_state"):
            thread_state = await self.memory_repository.get_thread_state(thread_id)
        latest_compaction = None
        if hasattr(self.memory_repository, "get_latest_conversation_compaction"):
            latest_compaction = await self.memory_repository.get_latest_conversation_compaction(
                thread_id
            )
        return thread_state, latest_compaction

    def _build_thread_state(
        self,
        thread_id: str,
        patient_id: Optional[str],
        existing_state: Optional[ThreadState],
        response_message: str,
        intent,
        conversation_context,
        result: dict,
    ) -> ThreadState:
        intent_plan = result.get("intent_plan") or {}
        allowed_domains = {member.value: member for member in DomainName}
        active_domains = [
            allowed_domains[domain]
            for domain in intent_plan.get("domains", [])
            if domain in allowed_domains
        ]
        if not active_domains and existing_state:
            active_domains = existing_state.active_domains

        active_task_type = None
        response_mode = intent_plan.get("response_mode")
        if response_mode and response_mode in {member.value for member in ResponseMode}:
            active_task_type = ResponseMode(response_mode)
        elif existing_state:
            active_task_type = existing_state.active_task_type

        pending_slots: list[str] = []
        if intent and not intent.is_ready:
            if not getattr(intent, "data_types", []):
                pending_slots.append("domain")
            if not getattr(intent, "date_range", None) and not getattr(
                intent, "month_filters", None
            ):
                pending_slots.append("time")

        return ThreadState(
            thread_id=thread_id,
            patient_id=patient_id,
            active_domains=active_domains,
            active_task_type=active_task_type,
            active_goal=intent_plan.get("requested_goal")
            or conversation_context.inherited_goal
            or (existing_state.active_goal if existing_state else None),
            active_date_scope=intent_plan.get("date_scope_label")
            or conversation_context.inherited_date_scope
            or (existing_state.active_date_scope if existing_state else None),
            last_assistant_question=response_message if response_message.strip().endswith("?") else None,
            pending_slots=pending_slots,
            summary=conversation_context.system_note(),
            last_assistant_response=response_message,
        )

    async def _build_and_save_thread_compaction(
        self,
        *,
        thread_id: str,
        patient_id: Optional[str],
        thread_state: ThreadState,
        conversation_context,
    ) -> Optional[ConversationCompaction]:
        if not self.conversation_repository:
            return None
        thread_history = await self.conversation_repository.get_thread_history(
            thread_id, limit=24
        )
        compaction = build_conversation_compaction(
            thread_id=thread_id,
            patient_id=patient_id,
            recent_messages=thread_history,
            thread_state=thread_state,
            conversation_context=conversation_context,
        )
        await self.memory_repository.save_conversation_compaction(compaction)
        return compaction

    def _convert_to_conversation_message(
        self, response_data: dict, user_message: str, thread_id: str
    ) -> ConversationMessage:
        intent_dict = {}
        if response_data.get("data_types"):
            intent_dict["data_types"] = response_data["data_types"]
        if response_data.get("date_range"):
            intent_dict["date_range"] = response_data["date_range"]
        if response_data.get("hour_range"):
            intent_dict["hour_range"] = response_data["hour_range"]
        if response_data.get("month_filters"):
            intent_dict["month_filters"] = response_data["month_filters"]
        if response_data.get("time_buckets"):
            intent_dict["time_buckets"] = response_data["time_buckets"]
        if response_data.get("numeric_filters"):
            intent_dict["numeric_filters"] = response_data["numeric_filters"]
        if response_data.get("suggestions"):
            intent_dict["suggestions"] = response_data["suggestions"]
        if response_data.get("confidence") is not None:
            intent_dict["confidence"] = response_data["confidence"]

        response_dict = {
            "message": response_data.get("message", ""),
            "is_ready": response_data.get("is_ready", False),
            "data_types": response_data.get("data_types"),
        }

        metadata = {
            "thread_id": thread_id,
            "turn_number": response_data.get("turn_number", 0),
            "message_count": response_data.get("message_count", 0),
        }
        if response_data.get("retrieval_metrics"):
            metadata["retrieval"] = response_data["retrieval_metrics"]

        return ConversationMessage(
            message_type="assistant",
            content=response_data.get("message", ""),
            timestamp=datetime.now(UTC),
            intent=intent_dict if intent_dict else None,
            response=response_dict if response_data.get("is_ready") else None,
            metadata=metadata,
        )

    async def process_message(
        self,
        user_message: str,
        thread_id: str = "default_session",
        user_id: Optional[str] = None,
        user_role: Optional[str] = None,
        patient_ids: Optional[list[str]] = None,
        debug: bool = False,
    ) -> Union[QueryResponse, ConversationMessage]:
        config = {"configurable": {"thread_id": thread_id}}

        if user_role:
            try:
                ProfileTypeEnum(user_role)
            except ValueError:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST, message="Invalid user role"
                )

        try:
            await self._ensure_storage_indexes()
        except Exception as e:
            logger.warning(f"Failed to initialize health agent indexes: {e}")

        await self._save_user_message(user_id, user_message, thread_id)

        recent_messages = self._get_conversation_messages(thread_id)
        memory_subject_id = self._resolve_memory_subject_id(user_id, user_role, patient_ids)
        patient_memory = await self.memory_repository.get_patient_memory(memory_subject_id)
        stored_thread_state, latest_compaction = await self._get_runtime_thread_state(
            thread_id
        )
        conversation_context = ConversationResolver.resolve(
            user_message=user_message,
            recent_messages=recent_messages,
            thread_state=stored_thread_state,
            patient_memory=patient_memory,
            latest_compaction=latest_compaction,
        )

        result = await self.app.ainvoke(
            {
                "messages": [{"role": "user", "content": user_message}],
                "patient_ids": patient_ids,
                "user_role": user_role,
                "conversation_context": conversation_context.model_dump(mode="json"),
                "patient_memory_facts": [
                    fact.model_dump(mode="json") for fact in patient_memory
                ],
                "thread_state": stored_thread_state.model_dump(mode="json")
                if stored_thread_state
                else None,
            },
            config,
        )
        intent = result.get("intent")

        source_messages = result.get("source_messages")
        if source_messages is None:
            state = self.app.get_state(config)
            source_messages = (
                state.values.get("messages", []) if state and state.values else []
            )

        response_data = self._build_response_data(
            result, user_message, intent, thread_id
        )
        await self._save_assistant_message(
            user_id,
            thread_id,
            intent,
            response_data,
            intent.is_ready if intent else False,
            source_messages=source_messages,
            retrieval_metadata=result.get("retrieval_metrics"),
        )

        await self.app.aupdate_state(
            config,
            {"messages": [{"role": "assistant", "content": response_data["message"]}]},
        )

        if conversation_context.explicit_facts:
            await self.memory_repository.upsert_patient_facts(
                memory_subject_id,
                conversation_context.explicit_facts,
            )

        new_thread_state = self._build_thread_state(
            thread_id=thread_id,
            patient_id=memory_subject_id,
            existing_state=stored_thread_state,
            response_message=response_data["message"],
            intent=intent,
            conversation_context=conversation_context,
            result=result,
        )
        await self.memory_repository.upsert_thread_state(new_thread_state)

        analysis_snapshot = result.get("analysis_snapshot")
        if analysis_snapshot:
            await self.memory_repository.save_analysis_snapshot(
                AnalysisSnapshot(**analysis_snapshot)
            )

        turn_number = response_data.get("turn_number", 0)
        if turn_number >= 4 and turn_number % 2 == 0:
            from lib.workers.tasks.health_query_agent.enqueue import (
                enqueue_health_query_compaction_async,
            )

            await enqueue_health_query_compaction_async(
                thread_id=thread_id,
                patient_id=memory_subject_id,
            )

        if debug:
            return QueryResponse(**response_data)
        return self._convert_to_conversation_message(
            response_data, user_message, thread_id
        )

    async def get_conversation_history(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        since: Optional[datetime] = None,
    ):
        if not self.conversation_repository:
            raise ValueError("Conversation repository not initialized")

        return await self.conversation_repository.get_conversation_history(
            user_id=user_id,
            limit=limit,
            offset=offset,
            since=since,
        )

    async def reset_conversation(
        self, thread_id: str, user_id: Optional[str] = None
    ) -> None:
        config = {"configurable": {"thread_id": thread_id}}
        try:
            await self.app.aupdate_state(config, {"messages": RESET, "intent": None})
            logger.info(
                f"Reset conversation for thread_id: {thread_id}, user_id: {user_id}"
            )
        except Exception as e:
            logger.warning(f"Failed to reset conversation state: {e}")

    async def compact_thread(
        self,
        thread_id: str,
        patient_id: Optional[str] = None,
    ) -> Optional[ConversationCompaction]:
        thread_state, latest_compaction = await self._get_runtime_thread_state(
            thread_id
        )
        recent_messages = self._get_conversation_messages(thread_id)
        conversation_context = ConversationResolver.resolve(
            user_message="",
            recent_messages=recent_messages,
            thread_state=thread_state,
            patient_memory=[],
            latest_compaction=latest_compaction,
        )
        effective_patient_id = patient_id or (thread_state.patient_id if thread_state else None)
        return await self._build_and_save_thread_compaction(
            thread_id=thread_id,
            patient_id=effective_patient_id,
            thread_state=thread_state
            or ThreadState(thread_id=thread_id, patient_id=effective_patient_id),
            conversation_context=conversation_context,
        )
