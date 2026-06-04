"""Backfill image_urls from image_url on patient_meals.

Run after the alembic migration that adds the image_urls column.
Idempotent — safe to re-run.

Usage:
    python scripts/backfill_meal_image_urls.py
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
                "SET image_urls = ARRAY[image_url] "
                "WHERE image_url IS NOT NULL AND image_urls IS NULL"
            )
        )
        print(f"Backfilled {result.rowcount} meals")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(backfill())
