"""One-time migration: move all vitals from Postgres to ClickHouse.

Usage:
    python scripts/migrate_vitals_to_clickhouse.py [--batch-size 10000] [--dry-run]

After verifying counts match, you can drop the Postgres patient_vitals table.
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


VITAL_FIELDS = [
    "heart_rate", "systolic_bp", "diastolic_bp", "spo2",
    "temperature", "respiratory_rate", "weight",
    "a1c", "creatinine", "ketones",
]

BATCH_SIZE = 10_000


async def migrate(batch_size: int, dry_run: bool):
    from lib.core.clickhouse_store import get_clickhouse_store
    from lib.dependencies.database import postgres_store
    from sqlalchemy import select, func
    from lib.models.patient_vital import PatientVital

    ch = get_clickhouse_store()
    ch.create_vitals_data_table()
    print("ClickHouse table aihealth.vitals_data ready.")

    # Count Postgres rows
    async with postgres_store.get_session() as session:
        count_result = await session.execute(select(func.count(PatientVital.id)))
        total_pg = count_result.scalar() or 0
    print(f"Postgres patient_vitals: {total_pg:,} rows")

    if dry_run:
        print("[DRY RUN] Would migrate rows. Exiting.")
        return

    migrated = 0
    ch_rows_written = 0
    offset = 0

    while offset < total_pg:
        async with postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientVital)
                .order_by(PatientVital.id)
                .limit(batch_size)
                .offset(offset)
            )
            batch = result.scalars().all()

        if not batch:
            break

        ch_batch: list[dict] = []
        for vital in batch:
            patient_id = str(vital.patient_id)
            vital_id = str(vital.id)
            test_time = vital.test_time
            source_name = vital.source_name or ""
            source_platform = vital.source_platform or ""

            for field in VITAL_FIELDS:
                value = getattr(vital, field, None)
                if value is not None:
                    ch_batch.append({
                        "patient_id": patient_id,
                        "vital_id": vital_id,
                        "type": field,
                        "value": float(value),
                        "time": test_time.replace(tzinfo=None),
                        "source_name": source_name,
                        "source_platform": source_platform,
                    })

        if ch_batch:
            ch.write_data("aihealth.vitals_data", ch_batch)
            ch_rows_written += len(ch_batch)

        migrated += len(batch)
        offset += batch_size
        print(f"  Migrated {migrated:,}/{total_pg:,} Postgres rows → {ch_rows_written:,} ClickHouse rows")

    # Verify
    ch_count = ch.client.execute("SELECT count() FROM aihealth.vitals_data")[0][0]
    print(f"\nDone. Postgres rows processed: {migrated:,}")
    print(f"ClickHouse rows written: {ch_rows_written:,}")
    print(f"ClickHouse total rows: {ch_count:,}")
    print(f"\nNote: ClickHouse has more rows than Postgres because each Postgres row")
    print(f"with multiple non-null fields expands into multiple ClickHouse rows (one per type).")

    if migrated == total_pg:
        print("\n✅ All Postgres rows processed. Safe to drop patient_vitals table after manual verification.")
    else:
        print(f"\n⚠️  Only {migrated}/{total_pg} rows processed. Re-run to complete.")


def main():
    parser = argparse.ArgumentParser(description="Migrate vitals from Postgres to ClickHouse")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    asyncio.run(migrate(args.batch_size, args.dry_run))


if __name__ == "__main__":
    main()
