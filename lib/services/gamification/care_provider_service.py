"""Care provider gamification views — engagement dashboard, at-risk detection, achievements starring."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import (
    DailyTask,
    PatientAchievement,
    PlayerProfile,
)
from lib.models.patient import Patient
from lib.models.associations import patient_care_provider_association
from lib.schemas.gamification import (
    CPGamificationOverview,
    PatientEngagementSummary,
    TaskStatus,
    title_for_level,
)
from lib.utils.postgres_session_decorator import with_postgres_session

AT_RISK_INACTIVE_DAYS = 3


class CPGamificationService:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    @with_postgres_session
    async def get_overview(
        self,
        care_provider_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> CPGamificationOverview:
        # Get all patients for this care provider
        result = await postgres_session.execute(
            select(patient_care_provider_association.c.patient_id).where(
                patient_care_provider_association.c.care_provider_id
                == care_provider_id
            )
        )
        patient_ids = list(result.scalars().all())
        if not patient_ids:
            return CPGamificationOverview(
                total_patients=0,
                active_patients=0,
                at_risk_patients=0,
                patients=[],
            )

        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        at_risk_cutoff = today - timedelta(days=AT_RISK_INACTIVE_DAYS)

        # Batch: all profiles for these patients
        profiles_result = await postgres_session.execute(
            select(PlayerProfile).where(
                PlayerProfile.patient_id.in_(patient_ids)
            )
        )
        profiles_by_id = {
            p.patient_id: p for p in profiles_result.scalars().all()
        }

        # Batch: all names
        names_result = await postgres_session.execute(
            select(Patient.patient_id, Patient.first_name).where(
                Patient.patient_id.in_(patient_ids)
            )
        )
        names_by_id = {row.patient_id: row.first_name for row in names_result.all()}

        # Batch: task counts per patient this week
        tasks_result = await postgres_session.execute(
            select(
                DailyTask.patient_id,
                func.count(DailyTask.task_id).label("cnt"),
            )
            .where(
                DailyTask.patient_id.in_(patient_ids),
                DailyTask.task_date >= week_start,
                DailyTask.status == TaskStatus.COMPLETED.value,
            )
            .group_by(DailyTask.patient_id)
        )
        tasks_by_id = {row.patient_id: row.cnt for row in tasks_result.all()}

        summaries: List[PatientEngagementSummary] = []
        active_count = 0
        at_risk_count = 0

        for pid in patient_ids:
            profile = profiles_by_id.get(pid)
            name = names_by_id.get(pid)
            tasks_this_week = tasks_by_id.get(pid, 0)

            level = profile.level if profile else 1
            streak = profile.current_streak if profile else 0
            xp = profile.total_xp if profile else 0
            last_active = profile.last_active_date if profile else None

            is_at_risk = (
                last_active is None or last_active < at_risk_cutoff
            )
            is_active = last_active is not None and last_active >= at_risk_cutoff

            if is_active:
                active_count += 1
            if is_at_risk:
                at_risk_count += 1

            summaries.append(
                PatientEngagementSummary(
                    patient_id=str(pid),
                    patient_name=name,
                    level=level,
                    title=title_for_level(level),
                    total_xp=xp,
                    current_streak=streak,
                    last_active_date=last_active,
                    tasks_completed_this_week=tasks_this_week,
                    is_at_risk=is_at_risk,
                )
            )

        # Sort: at-risk first, then by last active ascending
        summaries.sort(
            key=lambda s: (
                not s.is_at_risk,
                s.last_active_date or date.min,
            )
        )

        return CPGamificationOverview(
            total_patients=len(patient_ids),
            active_patients=active_count,
            at_risk_patients=at_risk_count,
            patients=summaries,
        )

    @with_postgres_session
    async def get_at_risk_patients(
        self,
        care_provider_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> List[PatientEngagementSummary]:
        overview = await self.get_overview(
            care_provider_id, postgres_session=postgres_session
        )
        return [p for p in overview.patients if p.is_at_risk]

    @with_postgres_session
    async def star_achievement(
        self,
        care_provider_id: UUID,
        patient_achievement_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        # Verify the patient belongs to this care provider
        result = await postgres_session.execute(
            select(PatientAchievement)
            .join(
                patient_care_provider_association,
                PatientAchievement.patient_id == patient_care_provider_association.c.patient_id,
            )
            .where(
                PatientAchievement.id == patient_achievement_id,
                patient_care_provider_association.c.care_provider_id == care_provider_id,
            )
        )
        pa = result.scalars().first()
        if not pa:
            raise ValueError("Patient achievement not found or not your patient")

        pa.starred_by = care_provider_id
        pa.starred_at = datetime.now().replace(tzinfo=None)
        await postgres_session.commit()
