"""Migrate ClickHouse tables from MergeTree to ReplacingMergeTree.

For each table: create new table with ReplacingMergeTree, copy data,
atomic rename swap, drop old backup.

Usage:
    python scripts/migrate_clickhouse_to_replacing_mergetree.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.core.clickhouse_store import get_clickhouse_store

TABLES = [
    {
        "name": "cgm_data",
        "ddl": """
        CREATE TABLE IF NOT EXISTS aihealth.cgm_data_new (
            patient_id String,
            time DateTime,
            glucose_level Float32,
            record_type String,
            source String DEFAULT 'unknown',
            INDEX idx_record_type record_type TYPE set(100) GRANULARITY 4,
            INDEX idx_source source TYPE set(100) GRANULARITY 4
        ) ENGINE = ReplacingMergeTree()
        ORDER BY (patient_id, time, source, record_type);
        """,
    },
    {
        "name": "fitness_data",
        "ddl": """
        CREATE TABLE IF NOT EXISTS aihealth.fitness_data_new (
            patient_id String,
            type String,
            source_name String,
            source_platform String,
            unit String,
            value Float64,
            start_datetime DateTime,
            end_datetime DateTime,
            INDEX idx_type type TYPE set(100) GRANULARITY 4,
            INDEX idx_source_name source_name TYPE set(100) GRANULARITY 4
        ) ENGINE = ReplacingMergeTree()
        ORDER BY (patient_id, type, start_datetime, source_name);
        """,
    },
    {
        "name": "sleep_data",
        "ddl": """
        CREATE TABLE IF NOT EXISTS aihealth.sleep_data_new (
            patient_id String,
            type String,
            source_name String,
            source_platform String,
            sleep_duration Float64,
            sleep_start_time DateTime,
            sleep_end_time DateTime,
            INDEX idx_type type TYPE set(100) GRANULARITY 4,
            INDEX idx_source_name source_name TYPE set(100) GRANULARITY 4
        ) ENGINE = ReplacingMergeTree()
        ORDER BY (patient_id, type, sleep_start_time, source_name);
        """,
    },
    {
        "name": "vitals_data",
        "ddl": """
        CREATE TABLE IF NOT EXISTS aihealth.vitals_data_new (
            patient_id String,
            vital_id String DEFAULT '',
            type String,
            value Float64,
            time DateTime,
            source_name String DEFAULT '',
            source_platform String DEFAULT '',
            INDEX idx_type type TYPE set(100) GRANULARITY 4,
            INDEX idx_source source_name TYPE set(100) GRANULARITY 4
        ) ENGINE = ReplacingMergeTree()
        ORDER BY (patient_id, type, time, source_name);
        """,
    },
]


def migrate(dry_run: bool):
    ch = get_clickhouse_store()

    for table in TABLES:
        name = table["name"]
        full = f"aihealth.{name}"
        full_new = f"aihealth.{name}_new"
        full_bak = f"aihealth.{name}_bak"

        old_count = ch.client.execute(f"SELECT count() FROM {full}")[0][0]
        print(f"\n{'='*50}")
        print(f"{full}: {old_count:,} rows")

        if dry_run:
            print(f"  [DRY RUN] Would migrate to ReplacingMergeTree")
            continue

        print(f"  Creating {full_new} with ReplacingMergeTree...")
        ch.client.execute(f"DROP TABLE IF EXISTS {full_new}")
        ch.client.execute(table["ddl"])

        print(f"  Copying data...")
        ch.client.execute(f"INSERT INTO {full_new} SELECT * FROM {full}")

        new_count = ch.client.execute(f"SELECT count() FROM {full_new}")[0][0]
        print(f"  Copied: {new_count:,} rows")

        if new_count != old_count:
            print(f"  ERROR: count mismatch ({old_count} vs {new_count}). Skipping swap.")
            ch.client.execute(f"DROP TABLE {full_new}")
            continue

        print(f"  Atomic swap: {name} -> {name}_bak, {name}_new -> {name}")
        ch.client.execute(f"DROP TABLE IF EXISTS {full_bak}")
        ch.client.execute(f"RENAME TABLE {full} TO {full_bak}, {full_new} TO {full}")

        print(f"  Dropping backup {full_bak}...")
        ch.client.execute(f"DROP TABLE {full_bak}")

        engine = ch.client.execute(f"SELECT engine FROM system.tables WHERE database='aihealth' AND name='{name}'")[0][0]
        print(f"  Done. Engine: {engine}")

    print(f"\n{'='*50}")
    print("Migration complete.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    migrate(args.dry_run)


if __name__ == "__main__":
    main()
