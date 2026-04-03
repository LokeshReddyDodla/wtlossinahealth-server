"""Shared helper for get-or-create PlayerProfile.

Used by XPService and StreakService — centralised here to avoid
identical race-condition-safe logic being copy-pasted.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.models.gamification import PlayerProfile


async def get_or_create_profile(
    patient_id: UUID, session: AsyncSession
) -> PlayerProfile:
    """Return the player's profile, creating one if it doesn't exist.

    Handles the race condition where two concurrent requests both try
    to create a profile: catches the IntegrityError from the unique
    constraint on patient_id, rolls back, and re-selects.
    """
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
            select(PlayerProfile).where(
                PlayerProfile.patient_id == patient_id
            )
        )
        profile = result.scalars().first()
        if profile:
            return profile
        raise
