"""Seed achievements table from the catalog. Idempotent — safe to call repeatedly."""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import Achievement
from lib.services.gamification.achievement_catalog import ACHIEVEMENT_CATALOG
from lib.utils.postgres_session_decorator import with_postgres_session


class AchievementSeeder:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    @with_postgres_session
    async def seed(self, *, postgres_session: AsyncSession) -> int:
        """Upsert all achievements from the catalog. Returns count of new achievements added."""
        result = await postgres_session.execute(select(Achievement.slug))
        existing_slugs = set(result.scalars().all())

        added = 0
        for entry in ACHIEVEMENT_CATALOG:
            if entry["slug"] in existing_slugs:
                # Update existing achievement fields (in case catalog changed)
                existing_result = await postgres_session.execute(
                    select(Achievement).where(Achievement.slug == entry["slug"])
                )
                achievement = existing_result.scalars().first()
                if achievement:
                    for key, value in entry.items():
                        if key != "slug" and hasattr(achievement, key):
                            setattr(achievement, key, value)
                continue

            achievement = Achievement(
                slug=entry["slug"],
                title=entry["title"],
                description=entry["description"],
                icon=entry["icon"],
                category=entry["category"],
                tier=entry["tier"],
                xp_reward=entry["xp_reward"],
                criteria_type=entry["criteria_type"],
                criteria_threshold=entry["criteria_threshold"],
                is_hidden=entry.get("is_hidden", False),
                is_progressive=entry.get("is_progressive", False),
                progressive_group=entry.get("progressive_group"),
                sort_order=entry.get("sort_order", 0),
            )
            postgres_session.add(achievement)
            added += 1

        await postgres_session.commit()
        if added:
            logger.info(f"Seeded {added} new achievements ({len(ACHIEVEMENT_CATALOG)} total in catalog)")
        return added
