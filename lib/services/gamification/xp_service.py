"""XP granting, ledger management, and level calculation."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.patient import Patient
from lib.models.gamification import PlayerProfile, XPLedgerEntry
from lib.services.gamification.time_utils import (
    local_today,
    naive_day_bounds_for_local_date,
)
from lib.schemas.gamification import title_for_level, xp_for_level
from lib.utils.postgres_session_decorator import with_postgres_session


# Streak multiplier breakpoints
_STREAK_MULTIPLIERS = [
    (90, 1.5),
    (60, 1.4),
    (30, 1.3),
    (14, 1.2),
    (7, 1.1),
]

DAILY_XP_CAP = 500


def streak_multiplier(streak: int) -> float:
    for threshold, mult in _STREAK_MULTIPLIERS:
        if streak >= threshold:
            return mult
    return 1.0


def level_from_xp(total_xp: int) -> int:
    """Return the highest level the player has reached."""
    level = 1
    while xp_for_level(level + 1) <= total_xp:
        level += 1
    return level


class XPService:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    @with_postgres_session
    async def grant_xp(
        self,
        patient_id: UUID,
        amount: int,
        source_type: str,
        description: str,
        *,
        source_id: Optional[UUID] = None,
        respect_cap: bool = True,
        postgres_session: AsyncSession,
    ) -> tuple[int, int, bool]:
        """Grant XP and return (xp_granted, new_level, leveled_up)."""
        profile = await self._get_or_create_profile(
            patient_id, postgres_session
        )

        multiplier = streak_multiplier(profile.current_streak)
        final_amount = int(math.ceil(amount * multiplier))
        tz_name = await self._patient_timezone(patient_id, postgres_session)

        if respect_cap:
            today_start, _ = naive_day_bounds_for_local_date(
                local_today(tz_name),
                tz_name,
            )
            result = await postgres_session.execute(
                select(func.coalesce(func.sum(XPLedgerEntry.xp_amount), 0))
                .where(
                    XPLedgerEntry.patient_id == patient_id,
                    XPLedgerEntry.created_at >= today_start,
                    XPLedgerEntry.xp_amount > 0,
                )
            )
            earned_today = result.scalar() or 0
            remaining = max(0, DAILY_XP_CAP - earned_today)
            final_amount = min(final_amount, remaining)

        if final_amount <= 0:
            return 0, profile.level, False

        entry = XPLedgerEntry(
            patient_id=patient_id,
            xp_amount=final_amount,
            source_type=source_type,
            source_id=source_id,
            description=description,
        )
        postgres_session.add(entry)

        old_level = profile.level
        profile.total_xp += final_amount
        new_level = level_from_xp(profile.total_xp)
        profile.level = new_level
        profile.title_slug = title_for_level(new_level).lower().replace(" ", "_")

        await postgres_session.commit()
        await postgres_session.refresh(profile)

        try:
            from lib.core.container import container
            from lib.services.gamification.challenge_service import ChallengeService

            challenge_service = container.resolve(ChallengeService)
            await challenge_service.update_participant_progress(
                patient_id=patient_id,
                metric_type="xp_earned",
                increment=float(final_amount),
            )
        except Exception:
            pass

        return final_amount, new_level, new_level > old_level

    @with_postgres_session
    async def get_xp_earned_today(
        self, patient_id: UUID, *, postgres_session: AsyncSession
    ) -> int:
        return await self.get_xp_earned_for_date(
            patient_id,
            local_today(await self._patient_timezone(patient_id, postgres_session)),
            postgres_session=postgres_session,
        )

    @with_postgres_session
    async def get_xp_earned_for_date(
        self,
        patient_id: UUID,
        target_date,
        *,
        tz_name: str | None = None,
        postgres_session: AsyncSession,
    ) -> int:
        today_start, today_end = naive_day_bounds_for_local_date(target_date, tz_name)
        result = await postgres_session.execute(
            select(func.coalesce(func.sum(XPLedgerEntry.xp_amount), 0))
            .where(
                XPLedgerEntry.patient_id == patient_id,
                XPLedgerEntry.created_at >= today_start,
                XPLedgerEntry.created_at <= today_end,
                XPLedgerEntry.xp_amount > 0,
            )
        )
        return result.scalar() or 0

    async def _get_or_create_profile(
        self, patient_id: UUID, session: AsyncSession
    ) -> PlayerProfile:
        result = await session.execute(
            select(PlayerProfile).where(PlayerProfile.patient_id == patient_id)
        )
        profile = result.scalars().first()
        if profile:
            return profile
        try:
            profile = PlayerProfile(patient_id=patient_id)
            session.add(profile)
            await session.flush()
            return profile
        except Exception:
            await session.rollback()
            result = await session.execute(
                select(PlayerProfile).where(PlayerProfile.patient_id == patient_id)
            )
            profile = result.scalars().first()
            if profile:
                return profile
            raise

    async def _patient_timezone(
        self,
        patient_id: UUID,
        session: AsyncSession,
    ) -> str | None:
        result = await session.execute(
            select(Patient.locale).where(Patient.patient_id == patient_id)
        )
        return result.scalar()
