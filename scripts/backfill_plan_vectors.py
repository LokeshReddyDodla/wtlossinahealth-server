"""Re-vectorize existing ACTIVE diet and fitness plans.

Plans saved before the ongoing-plan fix carry end_time == start_date in their
Qdrant point, so an open-ended plan is filtered out of any current-day query
and the brain never sees the patient's targets. Re-running the production
vectorizer rewrites each point with the corrected end_time (far-future for a
NULL end_date). Idempotent — deterministic point ids overwrite in place.

Run on the server (inside the docker network):
    python -m scripts.backfill_plan_vectors [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from lib.core.container import container
from lib.core.postgres_store import PostgresStore
from lib.dependencies.service_dependencies import (
    get_patient_diet_plan_service,
    get_patient_fitness_plan_service,
)
from lib.models.patient_diet_plan import PatientDietPlan
from lib.models.patient_fitness_plan import PatientFitnessPlan


async def main(dry_run: bool) -> None:
    store = container.resolve(PostgresStore)
    diet_service = get_patient_diet_plan_service()
    fitness_service = get_patient_fitness_plan_service()

    async with store.get_session() as session:
        diet_plans = (
            await session.execute(
                select(PatientDietPlan).where(PatientDietPlan.status == "ACTIVE")
            )
        ).scalars().all()
        fitness_plans = (
            await session.execute(
                select(PatientFitnessPlan).where(PatientFitnessPlan.status == "ACTIVE")
            )
        ).scalars().all()

    print(f"Active plans: {len(diet_plans)} diet, {len(fitness_plans)} fitness")
    if dry_run:
        print("--dry-run: no vectors written")
        return

    diet_ok = fitness_ok = 0
    for plan in diet_plans:
        await diet_service._vectorize_diet_plan(plan)
        diet_ok += 1
        if diet_ok % 50 == 0:
            print(f"  diet: {diet_ok}/{len(diet_plans)}")
    for plan in fitness_plans:
        await fitness_service._vectorize_fitness_plan(plan)
        fitness_ok += 1
        if fitness_ok % 50 == 0:
            print(f"  fitness: {fitness_ok}/{len(fitness_plans)}")

    print(f"Re-vectorized {diet_ok} diet + {fitness_ok} fitness plans")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Count plans without writing vectors")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
