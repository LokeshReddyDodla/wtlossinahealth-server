"""Migrate existing workouts to the new segments model.

Creates the patient_workout_segments table, backfills one segment per
existing workout from its type + duration_minutes, adds segment_id to
exercises, and wires up FK + index.

Idempotent: every step is guarded (IF NOT EXISTS, WHERE … IS NULL, etc.).
Re-run any number of times safely.

Run order:
  1. Deploy code with new models (PatientWorkoutSegment, updated relationships)
  2. Run this migration:  python scripts/migrate_workout_segments.py
  3. Verify:              python scripts/migrate_workout_segments.py --dry-run

Inside Docker:
    docker compose exec api python scripts/migrate_workout_segments.py
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402

from lib.core.postgres_store import PostgresStore  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("migrate_workout_segments")


# ── DDL steps (schema changes) ───────────────────────────────────────────

DDL_STEPS: list[tuple[str, str]] = [
    (
        "Create patient_workout_segments table",
        """
        CREATE TABLE IF NOT EXISTS patient_workout_segments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workout_id UUID NOT NULL REFERENCES patient_workouts(id) ON DELETE CASCADE,
            type VARCHAR NOT NULL,
            duration_minutes INTEGER,
            order_index INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now()
        )
        """,
    ),
    (
        "Create index on patient_workout_segments(workout_id)",
        """
        CREATE INDEX IF NOT EXISTS ix_workout_segments_workout
        ON patient_workout_segments(workout_id)
        """,
    ),
    (
        "Add segment_id column to patient_workout_exercises",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'patient_workout_exercises'
                  AND column_name = 'segment_id'
            ) THEN
                ALTER TABLE patient_workout_exercises
                ADD COLUMN segment_id UUID;
            END IF;
        END $$
        """,
    ),
]

DDL_POST_STEPS: list[tuple[str, str]] = [
    (
        "Add FK constraint exercise → segment",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_exercise_segment'
                  AND table_name = 'patient_workout_exercises'
            ) THEN
                ALTER TABLE patient_workout_exercises
                ADD CONSTRAINT fk_exercise_segment
                FOREIGN KEY (segment_id)
                REFERENCES patient_workout_segments(id) ON DELETE CASCADE;
            END IF;
        END $$
        """,
    ),
    (
        "Create index on patient_workout_exercises(segment_id)",
        """
        CREATE INDEX IF NOT EXISTS ix_workout_exercises_segment
        ON patient_workout_exercises(segment_id)
        """,
    ),
]


# ── DML steps (data backfill) ────────────────────────────────────────────
# Each entry: (label, count-query, backfill-query)

BACKFILLS: list[tuple[str, str, str]] = [
    (
        "Backfill segments from workouts (one segment per workout)",
        """
        SELECT COUNT(*) FROM patient_workouts w
        WHERE w.type IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM patient_workout_segments s
            WHERE s.workout_id = w.id
          )
        """,
        """
        INSERT INTO patient_workout_segments (id, workout_id, type, duration_minutes, order_index)
        SELECT gen_random_uuid(), w.id, w.type, w.duration_minutes, 0
        FROM patient_workouts w
        WHERE w.type IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM patient_workout_segments s
            WHERE s.workout_id = w.id
          )
        """,
    ),
    (
        "Link exercises to their workout's segment",
        """
        SELECT COUNT(*) FROM patient_workout_exercises e
        WHERE e.segment_id IS NULL
          AND e.workout_id IS NOT NULL
        """,
        """
        UPDATE patient_workout_exercises e
        SET segment_id = s.id
        FROM patient_workout_segments s
        WHERE s.workout_id = e.workout_id
          AND e.segment_id IS NULL
          AND e.workout_id IS NOT NULL
        """,
    ),
]


# ── Verification probes ──────────────────────────────────────────────────

PROBES: list[tuple[str, str]] = [
    (
        "Workouts with type but no segment (should be 0 after backfill)",
        "SELECT COUNT(*) FROM patient_workouts w "
        "WHERE w.type IS NOT NULL AND NOT EXISTS ("
        "  SELECT 1 FROM patient_workout_segments s WHERE s.workout_id = w.id"
        ")",
    ),
    (
        "Exercises with workout_id but no segment_id (should be 0 after backfill)",
        "SELECT COUNT(*) FROM patient_workout_exercises "
        "WHERE workout_id IS NOT NULL AND segment_id IS NULL",
    ),
    (
        "Total workouts",
        "SELECT COUNT(*) FROM patient_workouts",
    ),
    (
        "Total segments",
        "SELECT COUNT(*) FROM patient_workout_segments",
    ),
    (
        "Total exercises",
        "SELECT COUNT(*) FROM patient_workout_exercises",
    ),
]


async def run(dry_run: bool) -> None:
    store = PostgresStore()
    try:
        async with store.get_session() as session:
            # ── DDL: create table + columns ──
            if not dry_run:
                logger.info("─── Schema changes ───")
                for label, ddl_sql in DDL_STEPS:
                    await session.execute(text(ddl_sql))
                    logger.info(f"  ✓ {label}")
                await session.commit()

            # ── Pre-flight counts ──
            logger.info("─── Pre-flight: rows pending backfill ───")
            for label, count_sql, _ in BACKFILLS:
                result = await session.execute(text(count_sql))
                logger.info(f"  {label}: {result.scalar()} rows")

            if dry_run:
                logger.info("Dry-run mode — no data changes applied.")
            else:
                # ── Backfill data ──
                logger.info("─── Applying backfills ───")
                for label, _, update_sql in BACKFILLS:
                    result = await session.execute(text(update_sql))
                    logger.info(f"  ✓ {label}: {result.rowcount} rows")
                await session.commit()

                # ── Post-backfill DDL: FK + index ──
                logger.info("─── Post-backfill constraints ───")
                for label, ddl_sql in DDL_POST_STEPS:
                    await session.execute(text(ddl_sql))
                    logger.info(f"  ✓ {label}")
                await session.commit()

            # ── Verification ──
            logger.info("─── Verification ───")
            for label, probe_sql in PROBES:
                result = await session.execute(text(probe_sql))
                count = result.scalar()
                marker = "⚠️ " if "should be 0" in label and count else "  "
                logger.info(f"  {marker}{label}: {count}")

            logger.info("Done.")
    finally:
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate existing workouts to the segments model."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without writing.",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
