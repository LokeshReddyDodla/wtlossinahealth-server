from typing import List, Optional

from decouple import config
from motor.motor_asyncio import AsyncIOMotorClient

# Read MongoDB URL and credentials from env
MONGO_URL = config("MONGO_URL", default="mongodb://localhost:27017")
MONGO_DB_NAME = config("MONGO_DB_NAME", default="aihealth")


class MongoStore:
    def __init__(self):
        self.client = AsyncIOMotorClient(MONGO_URL)
        self.db = self.client[MONGO_DB_NAME]

    async def insert_document(self, collection_name: str, document: dict):
        collection = self.db[collection_name]
        result = await collection.insert_one(document)
        return result.inserted_id

    async def find_document(self, collection_name: str, query: dict):
        collection = self.db[collection_name]
        document = await collection.find_one(query)
        return document

    async def find_many(
        self,
        collection_name: str,
        query: dict,
        projection: Optional[dict] = None,
        session=None,
    ) -> List[dict]:
        collection = self.db[collection_name]
        cursor = collection.find(query, projection, session=session)
        documents = await cursor.to_list(length=None)
        return documents

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
