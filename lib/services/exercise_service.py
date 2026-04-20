"""Exercise catalog service — search, detail, facets over seeded exercise library."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.exercise import Exercise
from lib.schemas.exercise import (
    ExerciseFacetsResponse,
    ExerciseResponse,
    ExerciseSearchResponse,
)
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)


class ExerciseService:
    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store

    @staticmethod
    def to_response(row: Exercise) -> ExerciseResponse:
        return ExerciseResponse(
            id=row.id,
            name=row.name,
            force=row.force,
            level=row.level,
            mechanic=row.mechanic,
            equipment=row.equipment,
            category=row.category,
            primary_muscles=list(row.primary_muscles or []),
            secondary_muscles=list(row.secondary_muscles or []),
            instructions=list(row.instructions or []),
            image_urls=list(row.image_urls or []),
        )

    @with_postgres_session
    async def search(
        self,
        *,
        q: Optional[str] = None,
        muscle: Optional[list[str]] = None,
        equipment: Optional[list[str]] = None,
        category: Optional[list[str]] = None,
        level: Optional[list[str]] = None,
        limit: int = 20,
        offset: int = 0,
        postgres_session: AsyncSession,
    ) -> ExerciseSearchResponse:
        stmt = select(Exercise)
        count_stmt = select(func.count()).select_from(Exercise)

        if q:
            ts_query = func.plainto_tsquery("english", q)
            # Try tsvector first, fall back to ILIKE for rows with empty search_tsv
            text_filter = or_(
                Exercise.search_tsv.op("@@")(ts_query),
                Exercise.name.ilike(f"%{q}%"),
            )
            stmt = stmt.where(text_filter)
            count_stmt = count_stmt.where(text_filter)
            stmt = stmt.order_by(Exercise.name.asc())
        else:
            stmt = stmt.order_by(Exercise.name.asc())

        if muscle:
            muscle_filter = or_(*(Exercise.primary_muscles.any(m) for m in muscle))
            stmt = stmt.where(muscle_filter)
            count_stmt = count_stmt.where(muscle_filter)
        if equipment:
            stmt = stmt.where(Exercise.equipment.in_(equipment))
            count_stmt = count_stmt.where(Exercise.equipment.in_(equipment))
        if category:
            stmt = stmt.where(Exercise.category.in_(category))
            count_stmt = count_stmt.where(Exercise.category.in_(category))
        if level:
            stmt = stmt.where(Exercise.level.in_(level))
            count_stmt = count_stmt.where(Exercise.level.in_(level))

        stmt = stmt.limit(limit).offset(offset)

        total = (await postgres_session.execute(count_stmt)).scalar_one()
        rows = (await postgres_session.execute(stmt)).scalars().all()

        return ExerciseSearchResponse(
            total=total,
            limit=limit,
            offset=offset,
            items=[self.to_response(r) for r in rows],
        )

    @with_postgres_session
    async def get_by_id(
        self,
        exercise_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[ExerciseResponse]:
        row = (
            await postgres_session.execute(
                select(Exercise).where(Exercise.id == exercise_id)
            )
        ).scalar_one_or_none()
        return self.to_response(row) if row else None

    @with_postgres_session
    async def get_facets(
        self,
        *,
        postgres_session: AsyncSession,
    ) -> ExerciseFacetsResponse:
        muscle_col = func.unnest(Exercise.primary_muscles).label("muscle")
        muscles_q = select(muscle_col).distinct().order_by(muscle_col)
        equipment_q = (
            select(Exercise.equipment)
            .where(Exercise.equipment.isnot(None))
            .distinct()
            .order_by(Exercise.equipment)
        )
        categories_q = (
            select(Exercise.category).distinct().order_by(Exercise.category)
        )
        levels_q = select(Exercise.level).distinct().order_by(Exercise.level)

        muscles = (await postgres_session.execute(muscles_q)).scalars().all()
        equipment = (await postgres_session.execute(equipment_q)).scalars().all()
        categories = (await postgres_session.execute(categories_q)).scalars().all()
        levels = (await postgres_session.execute(levels_q)).scalars().all()

        return ExerciseFacetsResponse(
            muscles=list(muscles),
            equipment=list(equipment),
            categories=list(categories),
            levels=list(levels),
        )
