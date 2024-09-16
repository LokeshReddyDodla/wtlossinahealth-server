import json
import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorClient

from lib.core.mongo_store import get_mongo_store
from lib.managers.websocket_manager import WebSocketManager
from lib.pipelines.chat_pipelines import (get_group_chat_pipeline,
                                          get_individual_chat_pipeline)
from lib.services.socketio_service import sio
from lib.utils.serializers import serialize_message
from rest_server.chats.api_schema import (ChatMessage, ChatMessageCreate,
                                          MediaSchema)


class ChatService:
    def __init__(self):
        self.mongo_store = get_mongo_store()

    async def create_group_chat_for_patient(
        self,
        patient_id: str,
        patient_name: str,
        profile_picture: Optional[str] = None,
    ):
        chat_id = str(uuid.uuid4())
        group_chat = {
            "_id": chat_id,
            "is_group": True,
            "participants": [
                {
                    "id": patient_id,
                    "type": "patient",
                    "name": patient_name,
                    "profile_picture": profile_picture,
                }
            ],
            "messages": [],
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        await self.mongo_store.insert_document("group_chats", group_chat)
        return chat_id

    async def create_chat_instance(self, participants):
        chat_id = str(uuid.uuid4())
        chat_instance = {
            "_id": chat_id,
            "is_group": False,
            "participants": participants,
            "messages": [],
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        await self.mongo_store.insert_document("chats", chat_instance)
        return chat_id

    async def add_care_provider_to_group(
        self,
        group_chat_id: str,
        care_provider_id: str,
        care_provider_name: str,
        role: str,
        profile_picture: Optional[str] = None,
    ):
        pipeline = [
            {
                "$set": {
                    "updated_at": datetime.now(),
                    "participants": {
                        "$concatArrays": [
                            "$participants",
                            [
                                {
                                    "id": care_provider_id,
                                    "type": "care_provider",
                                    "name": care_provider_name,
                                    "role": role,
                                    "profile_picture": profile_picture,
                                }
                            ],
                        ]
                    },
                }
            }
        ]

        await self.mongo_store.db["group_chats"].update_one(
            {"_id": group_chat_id}, pipeline
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
            message_id=str(uuid.uuid4()),
            sender=message.sender,
            receiver=message.receiver if chat_type == "individual" else None,
            content=message.content,
            media=message.media,
            reply_to=message.reply_to,
            timestamp=message.timestamp,
            metadata=message.metadata,
            read_receipts=message.read_receipts,
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

    async def get_user_chats(self, user_id: str):
        # Pipeline for individual chats
        individual_pipeline = get_individual_chat_pipeline(user_id)
        group_pipeline = get_group_chat_pipeline(user_id)

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

    async def delete_related_chats(
        self, patient_id: str, delete_group_chat: bool = True
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

    async def find_group_chat_for_patient(self, patient_id: str):
        return await self.mongo_store.find_document(
            "group_chats",
            {
                "is_group": True,
                "participants": {"$elemMatch": {"id": patient_id}},
            },
        )
