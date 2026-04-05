"""Shared query helpers used across gamification services.

Centralises frequently repeated query patterns so that schema changes
(e.g., renaming GroupMember.is_active) require one edit, not six.
"""

from __future__ import annotations

from datetime import date
from typing import Any, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.models.gamification import (
    Challenge,
    ChallengeParticipant,
    GroupMember,
)
from lib.schemas.gamification import ParticipantStatus, ParticipantType


async def active_group_ids(
    patient_id: UUID, session: AsyncSession
) -> list[UUID]:
    """Return group IDs the patient is an active member of."""
    result = await session.execute(
        select(GroupMember.group_id).where(
            GroupMember.patient_id == patient_id,
            GroupMember.is_active == True,
        )
    )
    return list(result.scalars().all())


async def active_challenge_participations(
    patient_id: UUID,
    session: AsyncSession,
    *,
    metric_type: str | None = None,
    date_filter: date | None = None,
    active_only: bool = True,
    limit: int | None = None,
) -> list[Any]:
    """Return (ChallengeParticipant, Challenge) rows for a patient and their groups.

    Queries direct patient participations and participations through
    the patient's active groups, merges the results.
    """
    filters: list = []
    if active_only:
        filters.append(ChallengeParticipant.status == ParticipantStatus.ACTIVE.value)
        filters.append(Challenge.is_active == True)
    if metric_type:
        filters.append(Challenge.metric_type == metric_type)
    if date_filter:
        filters.append(Challenge.start_date <= date_filter)
        filters.append(Challenge.end_date >= date_filter)

    # Direct patient participations
    patient_q = (
        select(ChallengeParticipant, Challenge)
        .join(Challenge)
        .where(
            ChallengeParticipant.participant_id == patient_id,
            ChallengeParticipant.participant_type == ParticipantType.PATIENT.value,
            *filters,
        )
    )
    if limit:
        patient_q = patient_q.limit(limit)
    rows = list((await session.execute(patient_q)).all())

    # Group participations — exclude challenges the patient individually withdrew from
    group_ids = await active_group_ids(patient_id, session)
    if group_ids:
        withdrawn_challenge_ids = (
            select(ChallengeParticipant.challenge_id).where(
                ChallengeParticipant.participant_id == patient_id,
                ChallengeParticipant.participant_type == ParticipantType.PATIENT.value,
                ChallengeParticipant.status == "withdrawn",
            )
        ).scalar_subquery()

        group_q = (
            select(ChallengeParticipant, Challenge)
            .join(Challenge)
            .where(
                ChallengeParticipant.participant_id.in_(group_ids),
                ChallengeParticipant.participant_type == ParticipantType.GROUP.value,
                Challenge.challenge_id.notin_(withdrawn_challenge_ids),
                *filters,
            )
        )
        if limit:
            group_q = group_q.limit(limit)
        rows.extend((await session.execute(group_q)).all())

    return rows
