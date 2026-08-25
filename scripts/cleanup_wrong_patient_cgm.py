"""Wipe all CGM data for a patient who should never have had CGM uploaded.

Usage:
    python scripts/cleanup_wrong_patient_cgm.py <patient_id> [--dry-run]
"""

import asyncio
import sys

from loguru import logger


async def cleanup(patient_id: str, dry_run: bool) -> None:
    tag = "[DRY RUN] " if dry_run else ""

    from lib.core.container import container
    from lib.core.clickhouse_store import ClickHouseStore
    from lib.core.mongo_store import MongoStore
    from lib.core.qdrant_store import QdrantStore

    ch = container.resolve(ClickHouseStore)
    mongo = container.resolve(MongoStore)

    # ── 1. ClickHouse: raw CGM readings ──
    count_q = f"SELECT count() FROM aihealth.cgm_data WHERE patient_id = '{patient_id}'"
    count = ch.client.command(count_q)
    logger.info(f"{tag}ClickHouse cgm_data: {count} rows")
    if not dry_run and count:
        ch.client.command(
            f"ALTER TABLE aihealth.cgm_data DELETE WHERE patient_id = '{patient_id}'"
        )
        logger.info("  deleted")

    # ── 2. Mongo: CGM reports (daily/weekly/custom) ──
    cgm_coll = mongo.db["cgm_reports"]
    n = await cgm_coll.count_documents({"patient_id": patient_id})
    logger.info(f"{tag}Mongo cgm_reports: {n} docs")
    if not dry_run and n:
        r = await cgm_coll.delete_many({"patient_id": patient_id})
        logger.info(f"  deleted {r.deleted_count}")

    # ── 3. Mongo: meal reports have baked-in glucose_response / avg_glucose ──
    # Mark meal days dirty so the drain regenerates them WITHOUT glucose
    # (CGM rows are already gone from ClickHouse at this point).
    meal_coll = mongo.db["meal_reports"]
    pipeline = [
        {"$match": {"patient_id": patient_id, "report_type": "daily"}},
        {"$group": {"_id": "$date"}},
    ]
    meal_dates = [doc["_id"] async for doc in meal_coll.aggregate(pipeline) if doc["_id"]]
    logger.info(f"{tag}Mongo meal_reports: {len(meal_dates)} daily reports to regenerate")
    if not dry_run and meal_dates:
        from datetime import date as date_type
        from lib.derived.dirty import mark_dirty as _mark_dirty
        from lib.derived.registry import DataDomain
        parsed = []
        for d in meal_dates:
            if isinstance(d, str):
                parsed.append(date_type.fromisoformat(d))
            elif isinstance(d, datetime):
                parsed.append(d.date())
            elif isinstance(d, date_type):
                parsed.append(d)
        if parsed:
            await _mark_dirty(patient_id, DataDomain.MEAL, parsed, defer_s=0)
            logger.info(f"  marked {len(parsed)} meal days dirty for regeneration")

    # ── 4. Qdrant: CGM vectors ──
    from qdrant_client.http.models import Filter, FieldCondition, MatchValue
    qdrant = container.resolve(QdrantStore)
    async with qdrant.get_client() as client:
        cgm_filter = Filter(must=[
            FieldCondition(key="patient_id", match=MatchValue(value=patient_id)),
            FieldCondition(key="source", match=MatchValue(value="cgm")),
        ])
        # count first
        result = await client.scroll(
            collection_name="patient_data",
            scroll_filter=cgm_filter,
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        has_points = len(result[0]) > 0
        logger.info(f"{tag}Qdrant patient_data (cgm): {'has points' if has_points else 'empty'}")
        if not dry_run and has_points:
            await client.delete(
                collection_name="patient_data",
                points_selector=cgm_filter,
            )
            logger.info("  deleted")

    # ── 5. Postgres: clear last_cgm_reading_at on connected apps ──
    from lib.core.postgres_store import get_session
    from sqlalchemy import text
    async with get_session() as session:
        for table in ("patient_libreview", "patient_sinocare"):
            r = await session.execute(
                text(f"""
                    UPDATE {table} SET last_cgm_reading_at = NULL
                    WHERE connected_app_id IN (
                        SELECT id FROM patient_connected_apps
                        WHERE patient_id = :pid
                    ) AND last_cgm_reading_at IS NOT NULL
                """),
                {"pid": patient_id},
            )
            if r.rowcount:
                logger.info(f"{tag}Postgres {table}: cleared last_cgm_reading_at ({r.rowcount} rows)")
        if not dry_run:
            await session.commit()

    # ── 6. Derived dirty set: clear pending CGM drains ──
    try:
        from lib.derived.dirty import DirtyCell
        from lib.derived.registry import DataDomain
        async with get_session() as session:
            r = await session.execute(
                text("""
                    DELETE FROM derived_dirty
                    WHERE patient_id = :pid AND domain = :domain
                """),
                {"pid": patient_id, "domain": DataDomain.CGM.value},
            )
            if r.rowcount:
                logger.info(f"{tag}Postgres derived_dirty CGM: {r.rowcount} rows")
            if not dry_run:
                await session.commit()
    except Exception as e:
        logger.warning(f"derived_dirty cleanup skipped: {e}")

    logger.info(f"\n{'DRY RUN complete' if dry_run else 'CLEANUP DONE'} for patient {patient_id}")
    if not dry_run:
        logger.info("Meal reports marked dirty — the drain will regenerate them without glucose data.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/cleanup_wrong_patient_cgm.py <patient_id> [--dry-run]")
        sys.exit(1)

    patient_id = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    asyncio.run(cleanup(patient_id, dry_run))
