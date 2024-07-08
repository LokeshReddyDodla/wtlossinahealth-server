import os
from motor.motor_asyncio import AsyncIOMotorClient

# Read MongoDB URL from env
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

class MongoStore:
    def __init__(self):
        self.client = AsyncIOMotorClient(MONGO_URL)
        self.db = self.client["aihealth"]

    async def get_collection(self, collection_name):
        return self.db[collection_name]
