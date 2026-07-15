"""Restore SMBG readings from Qdrant vectors back into Postgres.

Reads all data_type=smbg points from Qdrant, resolves source_platform
from user_devices, and inserts any readings missing from patient_smbgs.
Silent — no vector generation or proactive events triggered.

Idempotent — skips readings that already exist by id.

Usage:
    python scripts/restore_smbg_from_qdrant.py          # dry-run (default)
    python scripts/restore_smbg_from_qdrant.py --apply   # actually insert
"""

import asyncio
import sys
from datetime import datetime
from uuid import UUID

from decouple import config
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = config("POSTGRES_ASYNCPG_URL")
QDRANT_HOST = config("QDRANT_HOST", default="aihealth-qdrant")
QDRANT_PORT = config("QDRANT_PORT", cast=int, default=6333)
QDRANT_COLLECTION = config("QDRANT_COLLECTION", default="patient_data")

DRY_RUN = "--apply" not in sys.argv


async def get_device_platforms(engine) -> dict[str, str]:
    """Build patient_id -> platform map from user_devices (most recent active device)."""
    async with engine.connect() as conn:
        rows = await conn.execute(text(
            "SELECT DISTINCT ON (user_id) user_id, device_type "
            "FROM user_devices "
            "WHERE profile_type = 'patient' AND device_type IS NOT NULL "
            "ORDER BY user_id, last_active_at DESC NULLS LAST"
        ))
        return {
            str(r.user_id): "ios" if r.device_type and "ios" in r.device_type.lower() else "android"
            for r in rows
        }


async def get_existing_smbg_ids(engine) -> set[str]:
    """Get all existing SMBG reading IDs from Postgres."""
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT id::text FROM patient_smbgs"))
        return {r[0] for r in rows}


async def scroll_all_smbg_vectors(qdrant: AsyncQdrantClient) -> list:
    """Scroll all smbg vectors from Qdrant."""
    points = []
    offset = None
    while True:
        result, next_offset = await qdrant.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=Filter(must=[
                FieldCondition(key="data_type", match=MatchValue(value="smbg")),
            ]),
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        points.extend(result)
        if next_offset is None:
            break
        offset = next_offset
    return points


def ms_to_datetime(ms) -> datetime:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000).replace(tzinfo=None)


async def restore():
    engine = create_async_engine(DATABASE_URL)
    qdrant = AsyncQdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=120)

    print("Loading device platforms...")
    platforms = await get_device_platforms(engine)
    print(f"  {len(platforms)} patients with devices")

    print("Loading existing SMBG IDs from Postgres...")
    existing_ids = await get_existing_smbg_ids(engine)
    print(f"  {len(existing_ids)} existing readings")

    print("Scrolling Qdrant for smbg vectors...")
    points = await scroll_all_smbg_vectors(qdrant)
    print(f"  {len(points)} smbg vectors found")

    to_insert = []
    skipped = 0
    for point in points:
        p = point.payload
        reading_id = p.get("reading_id")
        if not reading_id or reading_id in existing_ids:
            skipped += 1
            continue

        patient_id = p.get("patient_id")
        if not patient_id:
            skipped += 1
            continue

        reading_time = ms_to_datetime(p.get("reading_time"))
        uploaded_at = ms_to_datetime(p.get("uploaded_at"))
        if not reading_time:
            skipped += 1
            continue

        source_name = p.get("source", "app")
        source_platform = platforms.get(patient_id, "ios")

        to_insert.append({
            "id": reading_id,
            "patient_id": patient_id,
            "glucose_level": p.get("glucose_mgdl", 0),
            "reading_time": reading_time,
            "source_name": source_name,
            "source_platform": source_platform,
            "type": p.get("reading_type", "random"),
            "notes": p.get("notes") or None,
            "uploaded_at": uploaded_at or reading_time,
        })

    print(f"\n  {len(to_insert)} readings to restore, {skipped} skipped (already exist or invalid)")

    if not to_insert:
        print("Nothing to restore.")
        await engine.dispose()
        await qdrant.close()
        return

    # Group by patient for readable output
    by_patient: dict[str, int] = {}
    for row in to_insert:
        by_patient[row["patient_id"]] = by_patient.get(row["patient_id"], 0) + 1
    print("\nPer-patient breakdown:")
    for pid, count in sorted(by_patient.items(), key=lambda x: -x[1]):
        print(f"  {pid}: {count} readings")

    if DRY_RUN:
        print("\n  DRY RUN — no changes made. Pass --apply to insert.")
        await engine.dispose()
        await qdrant.close()
        return

    print("\nInserting into Postgres...")
    async with engine.begin() as conn:
        for row in to_insert:
            await conn.execute(
                text(
                    "INSERT INTO patient_smbgs "
                    "(id, patient_id, glucose_level, reading_time, source_name, "
                    "source_platform, type, notes, uploaded_at) "
                    "VALUES (:id, :patient_id, :glucose_level, :reading_time, "
                    ":source_name, :source_platform, :type, :notes, :uploaded_at) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": UUID(row["id"]),
                    "patient_id": UUID(row["patient_id"]),
                    "glucose_level": row["glucose_level"],
                    "reading_time": row["reading_time"],
                    "source_name": row["source_name"],
                    "source_platform": row["source_platform"],
                    "type": row["type"],
                    "notes": row["notes"],
                    "uploaded_at": row["uploaded_at"],
                },
            )
    print(f"  Restored {len(to_insert)} readings.")

    await engine.dispose()
    await qdrant.close()


if __name__ == "__main__":
    asyncio.run(restore())
