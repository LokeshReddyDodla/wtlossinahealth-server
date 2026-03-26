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
    ScalarQuantization,
    OptimizersConfigDiff,
    ScalarQuantizationConfig,
    ScalarType,
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
        # Qdrant client
        self.client: Optional[AsyncQdrantClient] = None
        self._indices_created: bool = False
        self._collection_ready: bool = False

    async def connect(self):
        """Connects to Qdrant. Only once per server lifetime."""
        if self.client:
            return  # already connected

        logger.info(f"🔌 Connecting to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}")
        try:
            self.client = AsyncQdrantClient(
                host=QDRANT_HOST, port=QDRANT_PORT, timeout=60,
                check_compatibility=False,
            )
            logger.info("✅ Qdrant connected")

            # Ensure collection & indices only once at startup
            await self.ensure_collection()
            await self.ensure_payload_indices()
        except Exception as e:
            logger.exception("❌ Failed to connect to Qdrant")
            raise

    async def ensure_collection(self):
        """Ensures collection exists. Runs once at startup."""
        if self._collection_ready:
            return

        async with self.get_client() as client:
            try:
                await client.get_collection(collection_name=QDRANT_COLLECTION)
                logger.info(
                    f"✅ Qdrant collection '{QDRANT_COLLECTION}' already exists"
                )
            except Exception:
                logger.info(f"🆕 Creating Qdrant collection '{QDRANT_COLLECTION}'")
                await client.recreate_collection(
                    collection_name=QDRANT_COLLECTION,
                    vectors_config=VectorParams(
                        size=3072, distance=Distance.COSINE, on_disk=True
                    ),
                    hnsw_config=HnswConfigDiff(
                        m=16,
                        ef_construct=100,
                        on_disk=True,
                    ),
                    quantization_config=ScalarQuantization(
                        scalar=ScalarQuantizationConfig(
                            type=ScalarType.INT8, always_ram=False
                        )
                    ),
                    optimizers_config=OptimizersConfigDiff(
                        default_segment_number=2,
                        indexing_threshold=20000,
                        memmap_threshold=20000,
                        flush_interval_sec=5,
                    ),
                )

        self._collection_ready = True

    async def ensure_payload_indices(self):
        """Creates payload indices. Only once at startup."""
        if self._indices_created:
            return

        fields_to_index: Dict[str, IntegerIndexParams | KeywordIndexParams] = {
            "start_time": IntegerIndexParams(
                type=IntegerIndexType.INTEGER, lookup=False, range=True
            ),
            "end_time": IntegerIndexParams(
                type=IntegerIndexType.INTEGER, lookup=False, range=True
            ),
            "month": IntegerIndexParams(
                type=IntegerIndexType.INTEGER, lookup=True, range=False
            ),
            "data_type": KeywordIndexParams(type=KeywordIndexType.KEYWORD),
            "time_of_day_bucket": KeywordIndexParams(type=KeywordIndexType.KEYWORD),
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
                        field_schema=index_params,
                    )
                    logger.debug(
                        f"Indexed payload field: {field_name} ({index_type_str})"
                    )
                except Exception as e:
                    if "already exists" not in str(e):
                        logger.warning(
                            f"⚠️ Could not create index for {field_name}: {e}"
                        )

        self._indices_created = True

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
        self, collection_name: str, points: list, chunk_size: int = 100
    ):
        """Efficiently upserts points in chunks."""
        total = len(points)
        async with self.get_client() as client:
            for i in range(0, len(points), chunk_size):
                chunk = points[i : i + chunk_size]
                await client.upsert(
                    collection_name=collection_name, points=chunk, wait=False
                )
                if (i // chunk_size + 1) % 10 == 0:
                    logger.info(
                        f"📤 Upserted {min(i + chunk_size, total)}/{total} points"
                    )

    async def close(self):
        """Closes Qdrant client (usually only on server shutdown)."""
        if self.client:
            await self.client.close()
            self.client = None
            logger.info("🛑 Qdrant client closed")
