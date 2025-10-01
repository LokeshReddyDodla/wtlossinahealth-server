import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from decouple import config
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams, Distance

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

QDRANT_HOST = config("QDRANT_HOST", default="aihealth-qdrant")
QDRANT_PORT = config("QDRANT_PORT", cast=int, default=6333)
QDRANT_COLLECTION = config("QDRANT_COLLECTION", default="patient_data")


class QdrantStore:
    _instance: Optional["QdrantStore"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(QdrantStore, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        self.client: AsyncQdrantClient | None = None

    async def connect(self):
        if not self.client:
            logger.info(
                f"🔌 Connecting to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}"
            )
            try:
                self.client = AsyncQdrantClient(
                    host=QDRANT_HOST, port=QDRANT_PORT
                )
                logger.info("✅ Qdrant connected")
                await self.ensure_collection()
            except Exception as e:
                logger.exception("❌ Failed to connect to Qdrant")
                raise

    async def ensure_collection(self):
        if not self.client:
            raise RuntimeError("Qdrant client not connected")

        async with self.get_client() as client:
            try:
                await client.get_collection(collection_name=QDRANT_COLLECTION)
                logger.info(
                    f"✅ Qdrant collection '{QDRANT_COLLECTION}' already exists"
                )
            except Exception:
                logger.info(
                    f"🆕 Creating Qdrant collection '{QDRANT_COLLECTION}'"
                )
                await client.recreate_collection(
                    collection_name=QDRANT_COLLECTION,
                    vectors_config=VectorParams(
                        size=1536, distance=Distance.COSINE
                    ),
                )

    @asynccontextmanager
    async def get_client(self) -> AsyncGenerator[AsyncQdrantClient, None]:
        if not self.client:
            await self.connect()
        try:
            yield self.client
        except Exception as e:
            logger.exception(f"Qdrant client encountered an error: {e}")
            raise

    async def close(self):
        if self.client:
            await self.client.close()
            self.client = None
            logger.info("🛑 Qdrant client closed")
