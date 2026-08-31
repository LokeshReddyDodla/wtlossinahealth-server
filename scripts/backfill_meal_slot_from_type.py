"""Backfill slot from the legacy type column on patient_meals.

slot is the primary field; type is a legacy fallback carrying the same value.
Idempotent — safe to re-run. Run before dropping the type column.

Usage:
    python scripts/backfill_meal_slot_from_type.py
"""

import asyncio

from decouple import config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = config("POSTGRES_ASYNCPG_URL")


async def backfill():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE patient_meals "
                "SET slot = type "
                "WHERE slot IS NULL AND type IS NOT NULL"
            )
        )
        print(f"Backfilled slot on {result.rowcount} meals")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(backfill())
