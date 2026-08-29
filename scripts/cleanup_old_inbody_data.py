"""Delete legacy InBody data that was migrated to the body-composition pipeline.

Targets:
  1. MongoDB patient_documents  — 179 InBody docs
  2. Postgres patient_inbody_reports — all rows
  3. Qdrant patient_data — vectors with data_type="inbody"

S3 originals under patients/{id}/documents/other/ are kept (cheap, harmless).

Usage:
    python -m scripts.cleanup_old_inbody_data                # dry-run
    python -m scripts.cleanup_old_inbody_data --delete       # real delete
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from qdrant_client.http.models import FieldCondition, Filter, MatchValue  # noqa: E402

from lib.core.mongo_store import MongoStore  # noqa: E402
from lib.core.postgres_store import PostgresStore  # noqa: E402
from lib.core.qdrant_store import QdrantStore  # noqa: E402
from lib.models.patient_inbody_report import PatientInbodyReport  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cleanup_old_inbody")

INBODY_QUERY = {
    "$or": [
        {"file.name": {"$regex": "InBody", "$options": "i"}},
        {"text_raw": {"$regex": "^InBody"}},
    ]
}
QDRANT_COLLECTION = "patient_data"
QDRANT_DATA_TYPE = "inbody"


async def count_mongo(collection) -> int:
    return await collection.count_documents(INBODY_QUERY)


async def delete_mongo(collection) -> int:
    result = await collection.delete_many(INBODY_QUERY)
    return result.deleted_count


async def count_postgres(pg: PostgresStore) -> int:
    from sqlalchemy import func, select

    async with pg.get_session() as session:
        row = await session.execute(select(func.count()).select_from(PatientInbodyReport))
        return row.scalar() or 0


async def delete_postgres(pg: PostgresStore) -> int:
    from sqlalchemy import delete

    async with pg.get_session() as session:
        result = await session.execute(delete(PatientInbodyReport))
        await session.commit()
        return result.rowcount


async def count_qdrant(qdrant: QdrantStore) -> int:
    filt = Filter(
        must=[FieldCondition(key="data_type", match=MatchValue(value=QDRANT_DATA_TYPE))]
    )
    async with qdrant.get_client() as client:
        resp = await client.count(collection_name=QDRANT_COLLECTION, count_filter=filt, exact=True)
        return resp.count


async def delete_qdrant(qdrant: QdrantStore) -> int:
    count = await count_qdrant(qdrant)
    filt = Filter(
        must=[FieldCondition(key="data_type", match=MatchValue(value=QDRANT_DATA_TYPE))]
    )
    async with qdrant.get_client() as client:
        await client.delete(collection_name=QDRANT_COLLECTION, points_selector=filt)
    return count


async def run(dry_run: bool) -> None:
    mongo = MongoStore()
    collection = mongo.get_collection("patient_documents")

    pg = PostgresStore()

    qdrant = QdrantStore()
    await qdrant.connect()

    mongo_count = await count_mongo(collection)
    pg_count = await count_postgres(pg)
    qdrant_count = await count_qdrant(qdrant)

    logger.info("--- Counts ---")
    logger.info(f"MongoDB patient_documents (InBody): {mongo_count}")
    logger.info(f"Postgres patient_inbody_reports:    {pg_count}")
    logger.info(f"Qdrant inbody vectors:              {qdrant_count}")

    if dry_run:
        logger.info("DRY RUN — pass --delete to remove")
        return

    deleted_mongo = await delete_mongo(collection)
    logger.info(f"Deleted {deleted_mongo} MongoDB docs")

    deleted_pg = await delete_postgres(pg)
    logger.info(f"Deleted {deleted_pg} Postgres rows")

    deleted_qd = await delete_qdrant(qdrant)
    logger.info(f"Deleted {deleted_qd} Qdrant vectors")

    logger.info("Done.")


def main():
    parser = argparse.ArgumentParser(description="Delete legacy InBody data")
    parser.add_argument("--delete", action="store_true", help="Actually delete (default is dry-run)")
    args = parser.parse_args()
    asyncio.run(run(dry_run=not args.delete))


if __name__ == "__main__":
    main()
