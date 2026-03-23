"""
MongoDB repository for storing and retrieving conversation history.
"""

import logging
from datetime import UTC, datetime
from typing import Optional, Dict, Any

from lib.core.mongo_store import MongoStore
from lib.services.health_query_agent.v2 import (
    ConversationHistoryResponse,
    ConversationMessage,
)

logger = logging.getLogger(__name__)

COLLECTION_NAME = "health_query_conversations"


class ConversationRepository:
    def __init__(self, mongo_store: MongoStore):
        self.mongo_store = mongo_store
        self.collection = mongo_store.get_collection(COLLECTION_NAME)

    async def ensure_indexes(self):
        """Create necessary indexes for efficient queries."""
        try:
            # Primary query index: user_id + created_at
            await self.collection.create_index(
                [("user_id", 1), ("created_at", 1)],
                name="user_timestamp_idx",
                background=True,
            )

            # Timestamp index for cleanup/analytics
            await self.collection.create_index(
                [("created_at", 1)],
                name="created_at_idx",
                background=True,
            )
            await self.collection.create_index(
                [("metadata.thread_id", 1), ("created_at", -1)],
                name="thread_timestamp_idx",
                background=True,
                sparse=True,
            )

            logger.info("Created indexes for health_query_conversations collection")
        except Exception as e:
            logger.warning(f"Error creating indexes (may already exist): {e}")

    async def save_message(
        self,
        user_id: str,
        message_type: str,
        content: str,
        intent: Optional[Dict[str, Any]] = None,
        response: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Save a message to conversation history.
        """
        try:
            document = {
                "user_id": user_id,
                "message_type": message_type,
                "content": content,
                "intent": intent,
                "response": response,
                "metadata": metadata or {},
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }

            result = await self.mongo_store.insert_document(COLLECTION_NAME, document)
            logger.debug(f"Saved message for user_id: {user_id}, type: {message_type}")
            return str(result)
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            raise

    async def get_conversation_history(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        since: Optional[datetime] = None,
    ) -> ConversationHistoryResponse:
        """
        Get conversation history for a user.
        """
        try:
            # Build query
            query = {"user_id": user_id}
            if since:
                query["created_at"] = {"$gte": since}

            # Get total count
            total_messages = await self.collection.count_documents(query)

            cursor = (
                self.collection.find(query)
                .sort("created_at", -1)
                .skip(offset)
                .limit(limit)
            )
            messages_docs = []
            async for doc in cursor:
                messages_docs.append(doc)

            # Convert to ConversationMessage objects
            messages = []
            for doc in messages_docs:
                message = ConversationMessage(
                    message_type=doc.get("message_type", "user"),
                    content=doc.get("content", ""),
                    timestamp=doc.get("created_at", datetime.now(UTC)),
                    intent=doc.get("intent"),
                    response=doc.get("response"),
                    metadata=doc.get("metadata"),
                )
                messages.append(message)

            return ConversationHistoryResponse(
                user_id=user_id,
                total_messages=total_messages,
                messages=messages,
            )
        except Exception as e:
            logger.error(f"Error retrieving conversation history: {e}")
            raise

    async def get_thread_history(self, thread_id: str, limit: int = 40) -> list[dict]:
        try:
            cursor = (
                self.collection.find({"metadata.thread_id": thread_id})
                .sort("created_at", -1)
                .limit(limit)
            )
            messages_docs = []
            async for doc in cursor:
                messages_docs.append(doc)
            messages_docs.reverse()
            return messages_docs
        except Exception as e:
            logger.error(f"Error retrieving thread history: {e}")
            raise

    async def delete_user_conversation(self, user_id: str) -> int:
        """
        Delete all conversation history for a user.
        """
        try:
            result = await self.mongo_store.delete_many_documents(
                COLLECTION_NAME, {"user_id": user_id}
            )
            logger.info(f"Deleted {result} messages for user_id: {user_id}")
            return result
        except Exception as e:
            logger.error(f"Error deleting conversation history: {e}")
            raise

    async def archive_user_conversation(self, user_id: str) -> int:
        """
        Archive conversation by adding archived flag (soft delete).
        """
        try:
            result = await self.mongo_store.update_many_documents(
                COLLECTION_NAME,
                {"user_id": user_id},
                {"$set": {"archived": True, "archived_at": datetime.now(UTC)}},
            )
            logger.info(f"Archived {result} messages for user_id: {user_id}")
            return result
        except Exception as e:
            logger.error(f"Error archiving conversation history: {e}")
            raise
