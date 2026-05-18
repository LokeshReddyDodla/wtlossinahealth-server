import os
from typing import List, Optional

from decouple import config
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Read MongoDB URL and credentials from env
load_dotenv()
MONGO_URL = os.getenv("MONGO_URL", default="mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", default="aihealth")


class MongoStore:
    def __init__(self):
        self.client = AsyncIOMotorClient(
            str(MONGO_URL),
        )
        self.db = self.client[str(MONGO_DB_NAME)]

    def get_collection(self, collection_name: str):
        return self.db[collection_name]

    # --- Index setup ---
    async def init_indexes(self):
        await self._init_ai_conversation_message_indexes()
        await self._init_support_ticket_indexes()
        await self._init_chat_indexes()
        # In future: await self._init_patient_indexes(), etc.

    async def _init_chat_indexes(self):
        """Indexes on chats + chat_messages. Pre-existing collections —
        adding these now because support tickets amplify the scan cost:
        every ticket detail load fetches the full thread by chat_id, and
        every chat list query filters by participants.id."""
        chats = self.db["chats"]
        await chats.create_index(
            [("participants.id", 1), ("updated_at", -1)],
            name="chat_participants_updatedAt_idx",
        )
        await chats.create_index([("kind", 1)], name="chat_kind_idx", sparse=True)

        messages = self.db["chat_messages"]
        await messages.create_index(
            [("chat_id", 1), ("timestamp", 1)],
            name="chatMessages_chatId_timestamp_idx",
        )

    async def _init_support_ticket_indexes(self):
        collection = self.db["support_tickets"]
        await collection.create_index(
            [("chat_id", 1)],
            name="support_chatId_unique_idx",
            unique=True,
        )
        await collection.create_index(
            [("requester_id", 1), ("status", 1), ("last_message_at", -1)],
            name="support_requester_inbox_idx",
        )
        await collection.create_index(
            [("scope", 1), ("status", 1), ("last_message_at", -1)],
            name="support_scope_queue_idx",
        )
        await collection.create_index(
            [
                ("scope", 1),
                ("health_facility_id", 1),
                ("status", 1),
                ("last_message_at", -1),
            ],
            name="support_facility_queue_idx",
        )

    async def _init_ai_conversation_message_indexes(self):
        collection = self.db["ai_conversation_messages"]

        await collection.create_index(
            [("conversation_id", 1), ("created_at", 1)],
            name="conversation_createdAt_idx",
        )
        await collection.create_index(
            [("sender_id", 1), ("sender_type", 1)],
            name="sender_idx",
            sparse=True,
        )
        await collection.create_index(
            [("conversation_type", 1)], name="conversationType_idx"
        )
        await collection.create_index(
            [("status", 1)],
            name="status_idx",
            sparse=True,
        )
        await collection.create_index(
            [("hidden_from_ui", 1)],
            name="hiddenFromUI_idx",
            sparse=True,
        )
        await collection.create_index(
            [("model", 1)],
            name="model_idx",
            sparse=True,
        )
        await collection.create_index(
            [("created_at", -1)], name="createdAt_desc_idx"
        )

    # --- CRUD methods below ---
    async def insert_document(self, collection_name: str, document: dict):
        collection = self.db[collection_name]
        result = await collection.insert_one(document)
        return result.inserted_id

    async def find_document(self, collection_name: str, query: dict):
        collection = self.db[collection_name]
        return await collection.find_one(query)

    async def find_many(
        self,
        collection_name: str,
        query: dict,
        projection: Optional[dict] = None,
        session=None,
    ) -> List[dict]:
        collection = self.db[collection_name]
        cursor = collection.find(query, projection, session=session)
        return await cursor.to_list(length=None)

    async def update_document(
        self, collection_name: str, query: dict, update: dict
    ):
        collection = self.db[collection_name]
        result = await collection.update_one(query, {"$set": update})
        return result.modified_count

    async def update_many_documents(
        self, collection_name: str, query: dict, update: dict, session=None
    ) -> int:
        collection = self.db[collection_name]
        result = await collection.update_many(query, update, session=session)
        return result.modified_count

    async def update_document_with_array_filters(
        self,
        collection_name: str,
        query: dict,
        update: dict,
        array_filters: Optional[List[dict]] = None,
    ):
        collection = self.db[collection_name]
        result = await collection.update_one(
            query, update, array_filters=array_filters
        )
        return result.modified_count

    async def delete_document(self, collection_name: str, query: dict):
        collection = self.db[collection_name]
        result = await collection.delete_one(query)
        return result.deleted_count

    async def delete_many_documents(
        self, collection_name: str, query: dict, session=None
    ) -> int:
        collection = self.db[collection_name]
        result = await collection.delete_many(query, session=session)
        return result.deleted_count


def get_mongo_store() -> MongoStore:
    return MongoStore()
