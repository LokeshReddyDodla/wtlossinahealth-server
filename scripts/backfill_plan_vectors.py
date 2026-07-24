"""Re-vectorize existing diet and fitness plans under the status-driven scheme.

Plans are now matched by plan_status (not date overlap), so every point must
carry a correct plan_status and real dates. This re-vectorizes ALL plans and
runs the expiry reconciliation once (ACTIVE plans past end_date -> EXPIRED),
bringing existing data in line with the new retrieval model. Idempotent —
deterministic point ids overwrite in place.

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

    if dry_run:
        async with store.get_session() as session:
            n_diet = len((await session.execute(select(PatientDietPlan))).scalars().all())
            n_fit = len((await session.execute(select(PatientFitnessPlan))).scalars().all())
        print(f"--dry-run: {n_diet} diet + {n_fit} fitness plans; no reconciliation, no writes")
        return

    # Expire first so the re-vectorize below reads reconciled status, not stale.
    diet_expired = await diet_service.expire_ended_plans()
    fitness_expired = await fitness_service.expire_ended_plans()
    print(f"Expired {diet_expired} diet + {fitness_expired} fitness plans")

    # Fresh read + vectorize inside the session so objects stay session-bound.
    async with store.get_session() as session:
        diet_plans = (await session.execute(select(PatientDietPlan))).scalars().all()
        fitness_plans = (await session.execute(select(PatientFitnessPlan))).scalars().all()
        print(f"Re-vectorizing {len(diet_plans)} diet + {len(fitness_plans)} fitness plans")
        for i, plan in enumerate(diet_plans, 1):
            await diet_service._vectorize_diet_plan(plan)
            if i % 50 == 0:
                print(f"  diet: {i}/{len(diet_plans)}")
        for i, plan in enumerate(fitness_plans, 1):
            await fitness_service._vectorize_fitness_plan(plan)
            if i % 50 == 0:
                print(f"  fitness: {i}/{len(fitness_plans)}")

    print(f"Done: {len(diet_plans)} diet + {len(fitness_plans)} fitness re-vectorized")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Count plans without writing")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
