from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import uuid

from lib.core.mongo_store import get_mongo_store


class ChatService:
    def __init__(self):
        self.mongo_store = get_mongo_store()

    async def create_group_chat_for_patient(
        self, patient_id: str, patient_name: str
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
        self, participant_id: str, new_name: str, participant_type: str
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
                    "updated_at": datetime.now(),
                }
            },
        )

    async def add_message(
        self,
        chat_id,
        sender_id,
        sender_type,
        content,
        reply_to=None,
        media_url=None,
    ):
        message = {
            "message_id": str(uuid.uuid4()),
            "sender_id": sender_id,
            "sender_type": sender_type,
            "content": content,
            "media_url": media_url,  # Optional field for images or attachments
            "reply_to": reply_to,  # Optional field for replies
            "timestamp": datetime.now(),
        }
        update = {
            "$push": {"messages": message},
            "$set": {"updated_at": datetime.now()},
        }
        return await self.mongo_store.update_document(
            "chats", {"_id": chat_id}, update
        )

    async def get_chat(self, chat_id):
        return await self.mongo_store.find_document("chats", {"_id": chat_id})

    async def update_context(self, chat_id, context):
        update = {"context": context, "updated_at": datetime.utcnow()}
        return await self.mongo_store.update_document(
            "chats", {"_id": chat_id}, update
        )

    async def get_context(self, chat_id):
        chat = await self.mongo_store.find_document("chats", {"_id": chat_id})
        return chat.get("context") if chat else None

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
