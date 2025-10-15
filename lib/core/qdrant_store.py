import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, Optional

from decouple import config
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    VectorParams,
    Distance,
    HnswConfigDiff,
    IntegerIndexParams,
    KeywordIndexParams,
    IntegerIndexType,
    KeywordIndexType,
)

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
                    host=QDRANT_HOST, port=QDRANT_PORT, timeout=60
                )
                logger.info("✅ Qdrant connected")
                await self.ensure_collection()
                await self.ensure_payload_indices()
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
                        size=3072, distance=Distance.COSINE
                    ),
                    hnsw_config=HnswConfigDiff(m=32, ef_construct=120),
                )

    async def ensure_payload_indices(self):
        """Creates payload indices for frequently filtered fields for optimization."""
        if not self.client:
            raise RuntimeError("Qdrant client not connected")

        fields_to_index: Dict[str, IntegerIndexParams | KeywordIndexParams] = {
            # Timestamps and Month use IntegerIndexParams
            "start_time": IntegerIndexParams(
                type=IntegerIndexType.INTEGER, lookup=False, range=True
            ),
            "end_time": IntegerIndexParams(
                type=IntegerIndexType.INTEGER, lookup=False, range=True
            ),
            "month": IntegerIndexParams(
                type=IntegerIndexType.INTEGER, lookup=True, range=False
            ),
            # Categorical fields use KeywordIndexParams
            "data_type": KeywordIndexParams(type=KeywordIndexType.KEYWORD),
            "time_of_day_bucket": KeywordIndexParams(
                type=KeywordIndexType.KEYWORD
            ),
            "patient_id": KeywordIndexParams(
                type=KeywordIndexType.KEYWORD, is_tenant=True
            ),
        }

        async with self.get_client() as client:
            for field_name, index_params in fields_to_index.items():
                index_type_str = index_params.__class__.__name__.replace(
                    "IndexParams", ""
                )

                try:
                    await client.create_payload_index(
                        collection_name=QDRANT_COLLECTION,
                        field_name=field_name,
                        field_schema=index_params,  # <-- Correctly assigned the class instance
                    )
                    logger.info(
                        f"✅ Indexed payload field: {field_name} ({index_type_str})"
                    )
                except Exception as e:
                    if "already exists" not in str(e):
                        logger.warning(
                            f"⚠️ Could not create index for {field_name}: {e}"
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

    async def upsert_points_chunked(
        self, collection_name: str, points: list, chunk_size: int = 200
    ):
        async with self.get_client() as client:
            for i in range(0, len(points), chunk_size):
                chunk = points[i : i + chunk_size]
                await client.upsert(
                    collection_name=collection_name, points=chunk
                )

    async def close(self):
        if self.client:
            await self.client.close()
            self.client = None
            logger.info("🛑 Qdrant client closed")
