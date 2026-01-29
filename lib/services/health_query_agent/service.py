"""
Agent service for processing user queries and managing conversations.
"""

import logging
from typing import Optional, Union
from datetime import datetime

from lib.core.cache_store import CacheStore
from lib.core.constants import ProfileTypeEnum
from lib.core.qdrant_store import QdrantStore
from lib.core.mongo_store import MongoStore
from lib.services.health_query_agent.serialization import to_checkpoint_safe
from .schemas import QueryResponse, ConversationMessage
from .workflow import build_workflow
from .conversation_repository import ConversationRepository
from lib.utils.http_exceptions import raise_http_exception
from fastapi import status
from lib.services.health_query_agent.state_constants import RESET

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
        self.conversation_repository = (
            ConversationRepository(mongo_store) if mongo_store else None
        )
        self.app = app or build_workflow(qdrant_store, cache_store=cache_store)

    # ---------------------- User/Assistant Message Storage ---------------------- #

    async def _save_user_message(self, user_id: str, user_message: str, thread_id: str):
        """Save a user message to MongoDB."""
        if not self.conversation_repository or not user_id:
            return

        try:
            await self.conversation_repository.save_message(
                user_id=user_id,
                message_type="user",
                content=user_message,
                metadata={
                    "thread_id": thread_id,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
        except Exception as e:
            logger.warning(f"Failed to save user message: {e}")

    async def _save_assistant_message(
        self,
        user_id: str,
        thread_id: str,
        intent,
        response_data: dict,
        is_ready: bool,
        source_messages: Optional[list] = None,
    ):
        """Save an assistant message to MongoDB."""
        if not self.conversation_repository or not user_id:
            return

        try:
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
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Add source messages that were used to generate this response
            if source_messages:
                metadata["source_messages"] = source_messages

            await self.conversation_repository.save_message(
                user_id=user_id,
                message_type="assistant",
                content=response_data["message"],
                intent=intent_dict,
                response=response_dict,
                metadata=metadata,
            )
        except Exception as e:
            logger.warning(f"Failed to save assistant message: {e}")

    # ---------------------- Conversation State Helpers ---------------------- #

    def _get_conversation_messages(self, thread_id: str) -> list:
        """Get messages from the current state for a thread."""
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
        """Construct structured response for the user message."""
        config = {"configurable": {"thread_id": thread_id}}
        state = self.app.get_state(config)
        messages = state.values.get("messages", []) if state and state.values else []
        turn_number = sum(1 for m in messages if m.get("role") == "user")

        # Base response
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

                # suggestions already cleaned
                response_data["suggestions"] = intent_dict.get("suggestions", [])

        return response_data

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

        return ConversationMessage(
            message_type="assistant",
            content=response_data.get("message", ""),
            timestamp=datetime.utcnow(),
            intent=intent_dict if intent_dict else None,
            response=response_dict if response_data.get("is_ready") else None,
            metadata=metadata,
        )

    # ---------------------- Public API ---------------------- #

    async def process_message(
        self,
        user_message: str,
        thread_id: str = "default_session",
        user_id: Optional[str] = None,
        user_role: Optional[str] = None,
        patient_ids: Optional[list[str]] = None,
        debug: bool = False,
    ) -> Union[QueryResponse, ConversationMessage]:
        """Process a user message and return structured response."""
        config = {"configurable": {"thread_id": thread_id}}

        # Validate user_role if provided
        if user_role:
            try:
                ProfileTypeEnum(user_role)
            except ValueError:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST, message="Invalid user role"
                )

        await self._save_user_message(user_id, user_message, thread_id)

        result = await self.app.ainvoke(
            {
                "messages": [{"role": "user", "content": user_message}],
                "patient_ids": patient_ids,
                "user_role": user_role,
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
        )

        if intent and intent.is_ready:
            try:
                await self.app.aupdate_state(
                    config, {"messages": RESET, "intent": None}
                )
            except Exception:
                pass

        if debug:
            return QueryResponse(**response_data)
        else:
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
        """Get conversation history for a user."""
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
        """Reset a conversation thread (clear active state)."""
        config = {"configurable": {"thread_id": thread_id}}
        try:
            await self.app.aupdate_state(config, {"messages": RESET, "intent": None})
            logger.info(
                f"Reset conversation for thread_id: {thread_id}, user_id: {user_id}"
            )
        except Exception as e:
            logger.warning(f"Failed to reset conversation state: {e}")
