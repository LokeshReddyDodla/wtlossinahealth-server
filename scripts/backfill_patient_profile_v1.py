"""Backfill new patient-profile v1 columns from legacy columns.

Idempotent: only fills new columns where they are NULL. Re-run any number
of times safely. Old columns are never modified.

Run order (Deploy 1):
  1. Apply schema migration:  alembic upgrade head
     (which creates the new columns: timezone, occupation, status,
      drinks_per_session, average_sleep_hours; type casts on years/duration)
  2. Run this backfill:        python scripts/backfill_patient_profile_v1.py
  3. Soak / verify:            psql -f docs/onboarding-soak-verification.sql
  4. Deploy the code that writes the new endpoint.

Usage:
    python scripts/backfill_patient_profile_v1.py            # apply
    python scripts/backfill_patient_profile_v1.py --dry-run  # show counts only

Inside Docker:
    docker compose exec api python scripts/backfill_patient_profile_v1.py
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
logger = logging.getLogger("backfill_patient_profile_v1")


# Each entry: (label, SELECT-count-query, UPDATE-query)
# Both queries are guarded with `WHERE new_col IS NULL` so re-running is safe.
BACKFILLS: list[tuple[str, str, str]] = [
    (
        "patients.timezone <- locale",
        "SELECT COUNT(*) FROM patients "
        "WHERE timezone IS NULL AND locale IS NOT NULL",
        "UPDATE patients SET timezone = locale "
        "WHERE timezone IS NULL AND locale IS NOT NULL",
    ),
    (
        "patients.height_cm <- height",
        "SELECT COUNT(*) FROM patients "
        "WHERE height_cm IS NULL AND height IS NOT NULL",
        "UPDATE patients SET height_cm = height "
        "WHERE height_cm IS NULL AND height IS NOT NULL",
    ),
    (
        "patients.weight_kg <- weight",
        "SELECT COUNT(*) FROM patients "
        "WHERE weight_kg IS NULL AND weight IS NOT NULL",
        "UPDATE patients SET weight_kg = weight "
        "WHERE weight_kg IS NULL AND weight IS NOT NULL",
    ),
    (
        "patients.waist_cm <- waist",
        "SELECT COUNT(*) FROM patients "
        "WHERE waist_cm IS NULL AND waist IS NOT NULL",
        "UPDATE patients SET waist_cm = waist "
        "WHERE waist_cm IS NULL AND waist IS NOT NULL",
    ),
    (
        "patient_smoking_habit.status <- smoke_status (+ disambiguate)",
        "SELECT COUNT(*) FROM patient_smoking_habit "
        "WHERE status IS NULL AND smoke_status IS NOT NULL",
        """
        UPDATE patient_smoking_habit
        SET status = CASE
            WHEN smoke_status = TRUE THEN 'CURRENT'
            WHEN smoke_status = FALSE
                 AND (COALESCE(quit_years_ago, 0) > 0
                      OR COALESCE(years_of_smoking, 0) > 0
                      OR COALESCE(cigarettes_per_day, 0) > 0)
                 THEN 'FORMER'
            WHEN smoke_status = FALSE THEN 'NEVER'
            ELSE NULL
        END
        WHERE status IS NULL AND smoke_status IS NOT NULL
        """,
    ),
    (
        "patient_alcohol_consumption.status <- consume_alcohol",
        "SELECT COUNT(*) FROM patient_alcohol_consumption "
        "WHERE status IS NULL AND consume_alcohol IS NOT NULL",
        """
        UPDATE patient_alcohol_consumption
        SET status = CASE
            WHEN consume_alcohol = TRUE AND COALESCE(frequency, '') = 'NEVER'
                THEN 'NEVER'
            WHEN consume_alcohol = TRUE  THEN 'REGULAR'
            WHEN consume_alcohol = FALSE THEN 'NEVER'
            ELSE NULL
        END
        WHERE status IS NULL AND consume_alcohol IS NOT NULL
        """,
    ),
    (
        "patient_alcohol_consumption.drinks_per_session <- quantity (regex)",
        r"""
        SELECT COUNT(*) FROM patient_alcohol_consumption
        WHERE drinks_per_session IS NULL
          AND quantity IS NOT NULL
          AND quantity ~ '\d+'
        """,
        r"""
        UPDATE patient_alcohol_consumption
        SET drinks_per_session = CAST(SUBSTRING(quantity FROM '\d+') AS INTEGER)
        WHERE drinks_per_session IS NULL
          AND quantity IS NOT NULL
          AND quantity ~ '\d+'
        """,
    ),
    (
        "patient_sleep_habit.average_sleep_hours <- average_sleep_duration (regex)",
        r"""
        SELECT COUNT(*) FROM patient_sleep_habit
        WHERE average_sleep_hours IS NULL
          AND average_sleep_duration IS NOT NULL
          AND average_sleep_duration ~ '\d'
        """,
        r"""
        UPDATE patient_sleep_habit
        SET average_sleep_hours = CAST(
            SUBSTRING(average_sleep_duration FROM '\d+\.?\d*') AS FLOAT
        )
        WHERE average_sleep_hours IS NULL
          AND average_sleep_duration IS NOT NULL
          AND average_sleep_duration ~ '\d'
        """,
    ),
    (
        "patient_food_allergies.name <- allergy_name (enum match else OTHER)",
        """
        SELECT COUNT(*) FROM patient_food_allergies
        WHERE name IS NULL AND allergy_name IS NOT NULL
        """,
        """
        UPDATE patient_food_allergies
        SET name = CASE
            WHEN UPPER(allergy_name) IN (
                'DAIRY','SHELLFISH','NUTS','TREE_NUTS','PEANUTS',
                'EGGS','GLUTEN','SOY','FISH','OTHER'
            ) THEN UPPER(allergy_name)
            ELSE 'OTHER'
        END,
        name_other = CASE
            WHEN UPPER(allergy_name) IN (
                'DAIRY','SHELLFISH','NUTS','TREE_NUTS','PEANUTS',
                'EGGS','GLUTEN','SOY','FISH','OTHER'
            ) THEN NULL
            ELSE allergy_name
        END
        WHERE name IS NULL AND allergy_name IS NOT NULL
        """,
    ),
    (
        "patient_drug_allergies.name <- allergy_name (enum match else OTHER)",
        """
        SELECT COUNT(*) FROM patient_drug_allergies
        WHERE name IS NULL AND allergy_name IS NOT NULL
        """,
        """
        UPDATE patient_drug_allergies
        SET name = CASE
            WHEN UPPER(allergy_name) IN (
                'PENICILLIN','NSAIDS','SULFA','ASPIRIN','OPIOIDS','OTHER'
            ) THEN UPPER(allergy_name)
            ELSE 'OTHER'
        END,
        name_other = CASE
            WHEN UPPER(allergy_name) IN (
                'PENICILLIN','NSAIDS','SULFA','ASPIRIN','OPIOIDS','OTHER'
            ) THEN NULL
            ELSE allergy_name
        END
        WHERE name IS NULL AND allergy_name IS NOT NULL
        """,
    ),
    (
        "patient_medical_histories.status <- 'CHRONIC' (default for legacy rows)",
        "SELECT COUNT(*) FROM patient_medical_histories "
        "WHERE status IS NULL AND condition IS NOT NULL",
        "UPDATE patient_medical_histories SET status = 'CHRONIC' "
        "WHERE status IS NULL AND condition IS NOT NULL",
    ),
    (
        "patient_eating_habits.dietary_preferences <- diet_preferences table",
        """
        SELECT COUNT(*) FROM patient_eating_habits eh
        WHERE eh.dietary_preferences IS NULL
          AND EXISTS (
            SELECT 1 FROM patient_diet_preferences dp
            WHERE dp.eating_habit_id = eh.eating_habit_id
          )
        """,
        """
        UPDATE patient_eating_habits eh
        SET dietary_preferences = ARRAY[dp.preference],
            diet_preferences_detail = dp.detail
        FROM patient_diet_preferences dp
        WHERE dp.eating_habit_id = eh.eating_habit_id
          AND eh.dietary_preferences IS NULL
        """,
    ),
    (
        "patient_reproductive_health <- pregnancy data from diabetic_history",
        """
        SELECT COUNT(*) FROM patient_diabetic_history dh
        WHERE dh.is_pregnant IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM patient_reproductive_health rh
            WHERE rh.patient_id = dh.patient_id
          )
        """,
        """
        INSERT INTO patient_reproductive_health
            (patient_id, is_pregnant, pregnancy_weeks)
        SELECT dh.patient_id, dh.is_pregnant, dh.pregnancy_weeks
        FROM patient_diabetic_history dh
        WHERE dh.is_pregnant IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM patient_reproductive_health rh
            WHERE rh.patient_id = dh.patient_id
          )
        """,
    ),
]


# Rows where we couldn't backfill — surfaced for manual review.
UNBACKFILLED_PROBES: list[tuple[str, str]] = [
    (
        "smoking rows with legacy data but no status",
        "SELECT COUNT(*) FROM patient_smoking_habit "
        "WHERE smoke_status IS NOT NULL AND status IS NULL",
    ),
    (
        "alcohol rows with legacy data but no status",
        "SELECT COUNT(*) FROM patient_alcohol_consumption "
        "WHERE consume_alcohol IS NOT NULL AND status IS NULL",
    ),
    (
        "alcohol rows with quantity but no drinks_per_session",
        "SELECT COUNT(*) FROM patient_alcohol_consumption "
        "WHERE quantity IS NOT NULL AND drinks_per_session IS NULL",
    ),
    (
        "sleep rows with duration string but no hours",
        "SELECT COUNT(*) FROM patient_sleep_habit "
        "WHERE average_sleep_duration IS NOT NULL AND average_sleep_hours IS NULL",
    ),
]


async def run(dry_run: bool) -> None:
    store = PostgresStore()
    try:
        async with store.get_session() as session:
            logger.info("─── Pre-flight: rows pending backfill ───")
            for label, count_sql, _ in BACKFILLS:
                result = await session.execute(text(count_sql))
                logger.info(f"  {label}: {result.scalar()} rows")

            if dry_run:
                logger.info("Dry-run mode — no updates applied.")
            else:
                logger.info("─── Applying backfills ───")
                for label, _, update_sql in BACKFILLS:
                    result = await session.execute(text(update_sql))
                    logger.info(f"  ✓ {label}: {result.rowcount} rows updated")
                await session.commit()
                logger.info("✅ Committed.")

            logger.info("─── Unbackfilled rows (manual review needed) ───")
            for label, probe_sql in UNBACKFILLED_PROBES:
                result = await session.execute(text(probe_sql))
                count = result.scalar()
                marker = "⚠️ " if count else "  "
                logger.info(f"  {marker}{label}: {count}")
    finally:
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be backfilled without writing.",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
