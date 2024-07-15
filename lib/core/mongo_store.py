from motor.motor_asyncio import AsyncIOMotorClient
from decouple import config


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

    async def update_document(
        self, collection_name: str, query: dict, update: dict
    ):
        collection = self.db[collection_name]
        result = await collection.update_one(query, {"$set": update})
        return result.modified_count

    async def delete_document(self, collection_name: str, query: dict):
        collection = self.db[collection_name]
        result = await collection.delete_one(query)
        return result.deleted_count


def get_mongo_store() -> MongoStore:
    return MongoStore()
