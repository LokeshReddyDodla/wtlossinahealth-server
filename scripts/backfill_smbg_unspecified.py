"""One-off: normalize legacy device-synced SMBG rows to the canonical type.

Device syncs wrote type="Unspecified" before 59161ae1; ingestion now writes
"random" and report fetches normalize at read — but the list API, timeline,
and RAG text still surface the raw stored value. Dry-run by default.

Usage: poetry run python scripts/backfill_smbg_unspecified.py [--apply]
"""

import asyncio
import sys

from sqlalchemy import func, select, update

from lib.core.postgres_store import PostgresStore
from lib.models.patient_smbg import PatientSMBG

VALID = ("fasting", "before_meal", "after_meal", "random")


async def main(apply: bool) -> None:
    store = PostgresStore()
    async with store.get_session() as session:
        count = (
            await session.execute(
                select(func.count()).where(PatientSMBG.type.notin_(VALID))
            )
        ).scalar_one()
        print(f"non-canonical SMBG rows: {count}")
        if not count:
            return
        if not apply:
            print("dry run — pass --apply to normalize them to 'random'")
            return
        await session.execute(
            update(PatientSMBG).where(PatientSMBG.type.notin_(VALID)).values(type="random")
        )
        await session.commit()
        print(f"normalized {count} rows to type='random'")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
