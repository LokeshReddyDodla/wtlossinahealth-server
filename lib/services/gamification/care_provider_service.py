"""Care provider gamification views — engagement dashboard, disengagement detection, achievements starring."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import (
    Challenge,
    ChallengeParticipant,
    DailyTask,
    Group,
    GroupMember,
    PatientAchievement,
    PlayerProfile,
)
from lib.models.patient import Patient
from lib.models.associations import patient_care_provider_association
from lib.schemas.gamification import (
    ChallengeResponse,
    CPGamificationOverview,
    CreatorType,
    GroupResponse,
    PatientEngagementSummary,
    TaskStatus,
    title_for_level,
)
from lib.utils.postgres_session_decorator import with_postgres_session

DISENGAGED_INACTIVE_DAYS = 3


class CPGamificationService:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    @with_postgres_session
    async def get_overview(
        self,
        care_provider_id: UUID,
        *,
        health_facility_id: Optional[UUID] = None,
        is_admin: bool = False,
        postgres_session: AsyncSession,
    ) -> CPGamificationOverview:
        # Must mirror the patient-list scope, or gamification and the roster
        # disagree on who's in the panel.
        if is_admin and health_facility_id:
            stmt = select(Patient.patient_id).where(
                Patient.health_facility_id == health_facility_id
            )
        elif is_admin:
            stmt = select(Patient.patient_id)
        else:
            stmt = select(patient_care_provider_association.c.patient_id).where(
                patient_care_provider_association.c.care_provider_id
                == care_provider_id
            )
        result = await postgres_session.execute(stmt)
        patient_ids = list(result.scalars().all())
        if not patient_ids:
            return CPGamificationOverview(
                total_patients=0,
                active_patients=0,
                disengaged_patients=0,
                patients=[],
            )

        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        inactive_cutoff = today - timedelta(days=DISENGAGED_INACTIVE_DAYS)

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

        # Panel task-completion this week = completed / total (all statuses).
        total_tasks_week = (
            await postgres_session.execute(
                select(func.count(DailyTask.task_id)).where(
                    DailyTask.patient_id.in_(patient_ids),
                    DailyTask.task_date >= week_start,
                )
            )
        ).scalar() or 0
        completed_tasks_week = sum(tasks_by_id.values())

        summaries: List[PatientEngagementSummary] = []
        active_count = 0
        disengaged_count = 0

        for pid in patient_ids:
            profile = profiles_by_id.get(pid)
            name = names_by_id.get(pid)
            tasks_this_week = tasks_by_id.get(pid, 0)

            level = profile.level if profile else 1
            streak = profile.current_streak if profile else 0
            xp = profile.total_xp if profile else 0
            last_active = profile.last_active_date if profile else None

            is_disengaged = (
                last_active is None or last_active < inactive_cutoff
            )
            is_active = last_active is not None and last_active >= inactive_cutoff

            if is_active:
                active_count += 1
            if is_disengaged:
                disengaged_count += 1

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
                    is_disengaged=is_disengaged,
                )
            )

        # Sort: disengaged first, then by last active ascending
        summaries.sort(
            key=lambda s: (
                not s.is_disengaged,
                s.last_active_date or date.min,
            )
        )

        avg_streak = round(
            sum(s.current_streak for s in summaries) / len(summaries), 1
        )
        completion_pct = (
            round(completed_tasks_week / total_tasks_week * 100, 1)
            if total_tasks_week
            else None
        )

        return CPGamificationOverview(
            total_patients=len(patient_ids),
            active_patients=active_count,
            disengaged_patients=disengaged_count,
            avg_streak=avg_streak,
            task_completion_pct=completion_pct,
            patients=summaries,
        )

    @with_postgres_session
    async def get_disengaged_patients(
        self,
        care_provider_id: UUID,
        *,
        health_facility_id: Optional[UUID] = None,
        is_admin: bool = False,
        postgres_session: AsyncSession,
    ) -> List[PatientEngagementSummary]:
        overview = await self.get_overview(
            care_provider_id,
            health_facility_id=health_facility_id,
            is_admin=is_admin,
            postgres_session=postgres_session,
        )
        return [p for p in overview.patients if p.is_disengaged]

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

    @with_postgres_session
    async def get_groups(
        self,
        care_provider_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> List[GroupResponse]:
        result = await postgres_session.execute(
            select(Group).where(
                Group.created_by_id == care_provider_id,
                Group.created_by_type == CreatorType.CARE_PROVIDER.value,
                Group.is_active == True,
            )
        )
        groups = result.scalars().all()
        from lib.services.gamification.group_service import GroupService

        responses: List[GroupResponse] = []
        for group in groups:
            count_result = await postgres_session.execute(
                select(func.count()).select_from(GroupMember).where(
                    GroupMember.group_id == group.group_id,
                    GroupMember.is_active == True,
                )
            )
            responses.append(
                GroupService.to_response(group, count_result.scalar() or 0)
            )
        return responses

    @with_postgres_session
    async def get_facility_challenges(
        self,
        facility_id: UUID,
        *,
        include_inactive: bool = False,
        postgres_session: AsyncSession,
    ) -> List[ChallengeResponse]:
        """All challenges in a health facility (created by any CP or admin)."""
        from lib.services.gamification.challenge_service import ChallengeService

        stmt = select(Challenge).where(Challenge.facility_id == facility_id)
        if not include_inactive:
            stmt = stmt.where(Challenge.is_active == True)
        result = await postgres_session.execute(
            stmt.order_by(Challenge.created_at.desc())
        )
        challenges = result.scalars().all()

        responses: List[ChallengeResponse] = []
        for challenge in challenges:
            count_result = await postgres_session.execute(
                select(func.count()).select_from(ChallengeParticipant).where(
                    ChallengeParticipant.challenge_id == challenge.challenge_id,
                    ChallengeParticipant.status.in_(["active", "completed"]),
                )
            )
            responses.append(
                ChallengeService._to_response(challenge, count_result.scalar() or 0)
            )
        return responses
