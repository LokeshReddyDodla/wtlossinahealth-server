from datetime import datetime
from typing import List, Optional

from pymongo.errors import PyMongoError

from lib.core.mongo_store import get_mongo_store
from lib.core.types import ProfileTypeLiteral
from lib.schemas.chat import ParticipantSchema
from lib.services.chat.base import BaseChatService


class ChatParticipantService(BaseChatService):
    def __init__(self):
        self.mongo_store = get_mongo_store()

    async def add_participant_in_chat(
        self,
        chat_id: str,
        user_id: str,
        type: ProfileTypeLiteral,
        is_read_only: Optional[bool] = False,
        is_muted: Optional[bool] = False,
        is_archived: Optional[bool] = False,
        is_pinned: Optional[bool] = False,
    ):
        """
        Add or update a participant in a chat.
        If the participant already exists, update their attributes. Otherwise, add them to the chat.
        """
        participant = ParticipantSchema(
            id=user_id,
            type=type,
            is_read_only=is_read_only,
            is_muted=is_muted,
            is_archived=is_archived,
            is_pinned=is_pinned,
        )
        participant_dict = participant.dict(by_alias=True)

        try:
            if await self._is_participant_in_chat(chat_id, user_id):
                # Update the existing participant
                await self._update_existing_participant(
                    chat_id, user_id, participant_dict
                )
            else:
                # Add the participant if they don't exist
                await self._add_new_participant(
                    chat_id, user_id, participant_dict
                )

        except PyMongoError as e:
            print(f"MongoDB Error while adding/updating participant: {e}")
            raise

    async def fetch_chat_participants(
        self,
        chat_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[dict]:
        if not chat_id and not user_id:
            raise ValueError("Either chat_id or user_id must be provided.")

        pipeline = self._build_participant_pipeline(chat_id, user_id)
        participants_cursor = self.mongo_store.db["chats"].aggregate(pipeline)

        participants = []
        async for participant in participants_cursor:
            participants.append(participant)

        return participants

    # Private Helper Methods
    async def _is_participant_in_chat(
        self, chat_id: str, user_id: str
    ) -> bool:
        """Check if a user is already a participant in a chat."""
        participant = await self.mongo_store.db["chats"].find_one(
            {"_id": chat_id, "participants.id": user_id},
            {"participants.$": 1},  # Fetch only the matching participant
        )
        return participant is not None

    async def _update_existing_participant(
        self, chat_id: str, user_id: str, participant_dict: dict
    ):
        """Update an existing participant's attributes in the chat."""
        await self.mongo_store.db["chats"].update_one(
            {"_id": chat_id, "participants.id": user_id},
            {
                "$set": {
                    "updated_at": datetime.now(),
                    "participants.$": participant_dict,
                }
            },
        )
        print(f"Updated participant {user_id} in chat {chat_id}.")

    async def _add_new_participant(
        self, chat_id: str, user_id: str, participant_dict: dict
    ):
        """Add a new participant to the chat."""
        await self.mongo_store.db["chats"].update_one(
            {"_id": chat_id},
            {
                "$set": {"updated_at": datetime.now()},
                "$push": {"participants": participant_dict},
                "$set": {f"unread_counts.{user_id}": 0},
            },
        )
        print(f"Added new participant {user_id} to chat {chat_id}.")

    def _build_participant_pipeline(
        self, chat_id: Optional[str], user_id: Optional[str]
    ) -> List[dict]:
        """
        Build a MongoDB aggregation pipeline for fetching participants based on chat_id or user_id.
        """
        match_stage = (
            {"_id": chat_id} if chat_id else {"participants.id": user_id}
        )

        return [
            {"$match": match_stage},
            {"$unwind": "$participants"},
            {
                "$group": {
                    "_id": "$participants.id",
                    "id": {"$first": "$participants.id"},
                    "type": {"$first": "$participants.type"},
                    "is_read_only": {"$first": "$participants.is_read_only"},
                    "is_muted": {"$first": "$participants.is_muted"},
                    "is_archived": {"$first": "$participants.is_archived"},
                    "is_pinned": {"$first": "$participants.is_pinned"},
                    "joined_at": {"$first": "$participants.joined_at"},
                }
            },
        ]
