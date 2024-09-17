import json
import uuid
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorClient

from lib.core.mongo_store import get_mongo_store
from lib.managers.websocket_manager import WebSocketManager
from lib.pipelines.chat_pipelines import get_chat_pipeline
from lib.schemas.chat import (GroupChatSchema, IndividualChatSchema,
                              ParticipantSchema)
from lib.schemas.chat_message import ChatMessage, ChatMessageCreate
from lib.services.socketio_service import sio
from lib.utils.serializers import serialize_message


class ChatService:
    def __init__(self):
        self.mongo_store = get_mongo_store()

    async def create_group_chat_for_patient(
        self,
        patient_id: str,
        patient_name: str,
        profile_picture: Optional[str] = None,
        is_read_only: Optional[bool] = False,
        is_muted: Optional[bool] = False,
        is_archived: Optional[bool] = False,
    ):
        participant = ParticipantSchema(
            id=patient_id,
            type="patient",
            name=patient_name,
            profile_picture=profile_picture,
            is_read_only=is_read_only,
            is_muted=is_muted,
            is_archived=is_archived,
        )

        group_chat = GroupChatSchema(
            is_group=True,
            participants=[participant],
        )
        group_chat_dict = group_chat.dict(by_alias=True)
        await self.mongo_store.insert_document("group_chats", group_chat_dict)
        return group_chat.id

    async def create_chat_instance(
        self, participants: List[ParticipantSchema]
    ):
        individual_chat = IndividualChatSchema(
            is_group=False, participants=participants
        )
        individual_chat_dict = individual_chat.dict(by_alias=True)
        await self.mongo_store.insert_document("chats", individual_chat_dict)
        return individual_chat.id

    async def add_care_provider_to_group(
        self,
        group_chat_id: str,
        care_provider_id: str,
        care_provider_name: str,
        role: str,
        profile_picture: Optional[str] = None,
    ):
        participant = ParticipantSchema(
            id=care_provider_id,
            type="care_provider",
            name=care_provider_name,
            profile_picture=profile_picture,
            is_read_only=False,
            is_muted=False,
            is_archived=False,
        )
        participant_dict = participant.dict()

        # Check if the participant already exists
        existing_participant = await self.mongo_store.db[
            "group_chats"
        ].find_one(
            {"_id": group_chat_id, "participants.id": care_provider_id},
            {"participants.$": 1},  # Fetch only the matching participant
        )

        if existing_participant:
            # Update the existing participant
            await self.mongo_store.db["group_chats"].update_one(
                {"_id": group_chat_id, "participants.id": care_provider_id},
                {
                    "$set": {
                        "updated_at": datetime.now(),
                        "participants.$": participant_dict,
                    }
                },
            )
        else:
            # Add the participant if they don't exist
            await self.mongo_store.db["group_chats"].update_one(
                {"_id": group_chat_id},
                {
                    "$set": {"updated_at": datetime.now()},
                    "$push": {"participants": participant_dict},
                },
            )

    async def update_participant_name(
        self,
        participant_id: str,
        new_name: str,
        profile_picture: Optional[str],
        participant_type: str,
    ):
        # Update group chats
        await self.mongo_store.db["group_chats"].update_many(
            {
                "participants.id": participant_id,
                "participants.type": participant_type,
            },
            {
                "$set": {
                    "participants.$.name": new_name,
                    "participants.$.profile_picture": profile_picture,
                    "updated_at": datetime.now(),
                }
            },
        )

        # Update 1v1 chats
        await self.mongo_store.db["chats"].update_many(
            {
                "is_group": False,
                "participants.id": participant_id,
                "participants.type": participant_type,
            },
            {
                "$set": {
                    "participants.$.name": new_name,
                    "participants.$.profile_picture": profile_picture,
                    "updated_at": datetime.now(),
                }
            },
        )

    async def add_message(
        self,
        chat_id: str,
        message: ChatMessageCreate,
        chat_type: Literal["individual", "group"] = "individual",
    ):
        message_data = ChatMessage(
            sender=message.sender,
            receiver=message.receiver if chat_type == "individual" else None,
            content=message.content,
            media=message.media,
            reply_to=message.reply_to,
            timestamp=message.timestamp,
            metadata=message.metadata,
            read_receipts=message.read_receipts,
            severity=message.severity or "low",
            is_flagged=message.is_flagged or False,
        )

        message_dict = message_data.dict()

        update = {
            "$push": {"messages": message_dict},
            "$set": {"updated_at": datetime.now()},
        }

        collection_name = "group_chats" if chat_type == "group" else "chats"

        try:
            await self.mongo_store.db[collection_name].update_one(
                {"_id": chat_id}, update
            )

            # Broadcast the message to WebSocket clients in the chat group
            await sio.emit(
                "message",
                {"room": chat_id, "message": serialize_message(message_dict)},
                room=chat_id,
            )

        except Exception as e:
            raise Exception(f"Failed to add message: {str(e)}")

    async def get_user_chats(
        self,
        user_id: str,
        fetch_last_message: bool = False,
        fetch_all_messages: bool = False,
    ):
        # Pipeline for individual chats
        individual_pipeline = get_chat_pipeline(
            user_id,
            fetch_last_message=fetch_last_message,
            fetch_all_messages=fetch_all_messages,
            is_group=False,
        )
        group_pipeline = get_chat_pipeline(
            user_id,
            fetch_last_message=fetch_last_message,
            fetch_all_messages=fetch_all_messages,
            is_group=True,
        )

        try:
            # Fetch individual chats
            individual_chats = (
                await self.mongo_store.db["chats"]
                .aggregate(individual_pipeline)
                .to_list(length=None)
            )

            # Fetch group chats
            group_chats = (
                await self.mongo_store.db["group_chats"]
                .aggregate(group_pipeline)
                .to_list(length=None)
            )

            # Combine results
            combined_chats = individual_chats + group_chats
            
            if fetch_last_message:
                combined_chats.sort(
                    key=lambda chat: (
                        chat["last_message"]["timestamp"]
                        if chat["last_message"]
                        else datetime.min
                    ),
                    reverse=True,
                )

            return combined_chats
        except Exception as e:
            raise Exception(f"Failed to fetch chats: {str(e)}")

    async def delete_all_related_chats(
        self,
        patient_id: str,
        delete_group_chat: bool = True,
    ):
        if delete_group_chat:
            group_chat = await self.find_group_chat_for_patient(patient_id)
            if group_chat:
                await self.mongo_store.delete_document(
                    "group_chats", {"_id": group_chat["_id"]}
                )

        # Find and delete all 1v1 chats involving the patient
        one_on_one_chats = (
            await self.mongo_store.db["chats"]
            .find(
                {
                    "is_group": False,
                    "participants": {"$elemMatch": {"id": patient_id}},
                }
            )
            .to_list(length=None)
        )

        for chat in one_on_one_chats:
            await self.mongo_store.delete_document(
                "chats", {"_id": chat["_id"]}
            )

    async def delete_patient_careprovider_chats(
        self,
        patient_id: str,
        care_provider_id: str,
    ):
        """
        Delete all 1v1 chats between a specific patient and care provider.
        This function excludes group chats and only targets individual chats
        where participants are the specified patient and care provider.
        """

        # Find and delete all 1v1 chats involving the specific patient and care provider
        patient_careprovider_chats = (
            await self.mongo_store.db["chats"]
            .find(
                {
                    "is_group": False,  # Exclude group chats
                    "participants": {
                        "$size": 2,  # Ensure there are exactly two participants
                        "$all": [
                            {
                                "$elemMatch": {
                                    "id": patient_id,
                                    "type": "patient",
                                }
                            },
                            {
                                "$elemMatch": {
                                    "id": care_provider_id,
                                    "type": "care_provider",
                                }
                            },
                        ],
                    },
                }
            )
            .to_list(length=None)
        )

        for chat in patient_careprovider_chats:
            await self.mongo_store.delete_document(
                "chats", {"_id": chat["_id"]}
            )

    async def find_group_chat_for_patient(self, patient_id: str):
        return await self.mongo_store.find_document(
            "group_chats",
            {
                "is_group": True,
                "participants": {"$elemMatch": {"id": patient_id}},
            },
        )
