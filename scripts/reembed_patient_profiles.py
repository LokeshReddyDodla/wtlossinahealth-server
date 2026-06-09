"""One-shot re-embed of every patient's profile vector.

The vector text_builder + payload were updated to consume new clean fields
(severity, smoke_type, snores, reproductive_health, etc.). Existing Qdrant
entries are still in the old shape because we only re-embed on PATCH —
idle patients who haven't been touched since the change keep their stale
representation.

This script walks every patient, builds the profile dict, and enqueues a
vector job. The arq worker handles the actual embedding asynchronously.
arq's job_id dedup (bucketed by minute in _enqueue_profile_vector) means
re-running this is safe — it won't double-embed anyone.

Usage:
    python scripts/reembed_patient_profiles.py            # apply
    python scripts/reembed_patient_profiles.py --dry-run  # report only
    python scripts/reembed_patient_profiles.py --limit 50 # subset

Inside Docker:
    docker compose exec api python scripts/reembed_patient_profiles.py
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.future import select  # noqa: E402
from sqlalchemy.orm import joinedload, selectinload  # noqa: E402

from lib.core.postgres_store import PostgresStore  # noqa: E402
from lib.models.patient import Patient  # noqa: E402
from lib.models.patient_eating_habit import PatientEatingHabit  # noqa: E402
from lib.models.patient_package_assignment import (  # noqa: E402
    PatientPackageAssignment,
)
from lib.schemas.patient import CorePatientProfile  # noqa: E402
from lib.workers.tasks.profile.enqueue import (  # noqa: E402
    enqueue_generate_profile_vector_async,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("reembed_patient_profiles")


async def run(dry_run: bool, limit: int | None) -> None:
    store = PostgresStore()
    try:
        async with store.get_session() as session:
            stmt = (
                select(Patient)
                .options(
                    joinedload(Patient.care_providers),
                    joinedload(Patient.package_assignments).options(
                        selectinload(PatientPackageAssignment.package)
                    ),
                    joinedload(Patient.health_facility),
                    selectinload(Patient.daily_activity),
                    selectinload(Patient.food_allergies),
                    selectinload(Patient.drug_allergies),
                    selectinload(Patient.alcohol_consumption),
                    selectinload(Patient.smoking_habit),
                    selectinload(Patient.sleep_habit),
                    joinedload(Patient.eating_habit).joinedload(
                        PatientEatingHabit.meal_timings
                    ),
                    joinedload(Patient.eating_habit).joinedload(
                        PatientEatingHabit.diet_preferences
                    ),
                    selectinload(Patient.diet_plans),
                    selectinload(Patient.fitness_plans),
                    selectinload(Patient.diabetic_history),
                    selectinload(Patient.reproductive_health),
                    selectinload(Patient.family_diabetic_histories),
                    selectinload(Patient.medical_histories),
                )
            )
            if limit:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            patients = result.unique().scalars().all()

            total = len(patients)
            logger.info(f"─── Walking {total} patient profiles ───")

            enqueued = 0
            skipped = 0
            errored = 0

            for i, patient in enumerate(patients, start=1):
                pid = str(patient.patient_id)
                try:
                    profile_data = CorePatientProfile.from_orm(patient).model_dump(
                        mode="json"
                    )
                    if dry_run:
                        skipped += 1
                    else:
                        job_id = await enqueue_generate_profile_vector_async(
                            pid, profile_data
                        )
                        if job_id:
                            enqueued += 1
                        else:
                            # arq dedup dropped it — usually means a fresh
                            # enqueue happened within the same minute bucket.
                            skipped += 1
                except Exception as e:
                    errored += 1
                    logger.warning(f"  ⚠️  {pid}: {e}")

                if i % 100 == 0:
                    logger.info(
                        f"  progress: {i}/{total} "
                        f"(enqueued={enqueued}, skipped={skipped}, errored={errored})"
                    )

            logger.info("─── Done ───")
            logger.info(f"  total patients:     {total}")
            logger.info(f"  enqueued:           {enqueued}")
            logger.info(f"  skipped/deduped:    {skipped}")
            logger.info(f"  errored:            {errored}")
            if dry_run:
                logger.info("Dry-run mode — no jobs were enqueued.")
            else:
                logger.info(
                    "Re-embedding runs in the background. "
                    "Check arq worker logs for progress."
                )
    finally:
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Walk patients without enqueueing any jobs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N patients (useful for a smoke test).",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()
