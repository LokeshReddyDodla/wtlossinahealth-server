"""
Agent service for processing user queries and managing conversations.
"""

import logging
from typing import Optional
from datetime import datetime

from lib.core.qdrant_store import QdrantStore
from lib.core.mongo_store import MongoStore
from lib.services.health_query_agent.serialization import to_checkpoint_safe
from .schemas import QueryResponse
from .workflow import build_workflow
from .conversation_repository import ConversationRepository
import redis

logger = logging.getLogger(__name__)


class HealthQueryAgentService:
    def __init__(
        self,
        qdrant_store: QdrantStore,
        mongo_store: Optional[MongoStore] = None,
        redis_client: Optional[redis.Redis] = None,
        app=None,
    ):
        self.qdrant_store = qdrant_store
        self.mongo_store = mongo_store
        self.conversation_repository = (
            ConversationRepository(mongo_store) if mongo_store else None
        )
        self.app = app or build_workflow(qdrant_store, redis_client=redis_client)

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

            await self.conversation_repository.save_message(
                user_id=user_id,
                message_type="assistant",
                content=response_data["message"],
                intent=intent_dict,
                response=response_dict,
                metadata={
                    "thread_id": thread_id,
                    "turn_number": response_data.get("turn_number", 0),
                    "timestamp": datetime.utcnow().isoformat(),
                },
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

    def _build_response_data(self, result: dict, user_message: str, intent) -> dict:
        """Construct structured response for the user message."""
        messages = result.get("messages", [])
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

    # ---------------------- Public API ---------------------- #

    async def process_message(
        self,
        user_message: str,
        thread_id: str = "default_session",
        user_id: Optional[str] = None,
        patient_ids: Optional[list[str]] = None,
    ) -> QueryResponse:
        """Process a user message and return structured response."""
        config = {"configurable": {"thread_id": thread_id}}

        await self._save_user_message(user_id, user_message, thread_id)

        messages = self._get_conversation_messages(thread_id)
        messages.append({"role": "user", "content": user_message})

        result = await self.app.ainvoke(
            {
                "messages": messages,
                "patient_ids": patient_ids,
            },
            config,
        )
        intent = result.get("intent")

        response_data = self._build_response_data(result, user_message, intent)
        await self._save_assistant_message(
            user_id,
            thread_id,
            intent,
            response_data,
            intent.is_ready if intent else False,
        )

        if intent and intent.is_ready:
            try:
                await self.app.aupdate_state(config, {"messages": []})
            except Exception:
                pass

        return QueryResponse(**response_data)

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
            await self.app.aupdate_state(config, {"messages": []})
            logger.info(
                f"Reset conversation for thread_id: {thread_id}, user_id: {user_id}"
            )
        except Exception as e:
            logger.warning(f"Failed to reset conversation state: {e}")
