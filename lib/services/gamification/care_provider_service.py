"""Care provider gamification views — engagement dashboard, disengagement detection, achievements starring."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
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
    CPLeaderboardEntry,
    CPLeaderboardResponse,
    CreatorType,
    GroupResponse,
    LeaderboardMetric,
    PatientEngagementSummary,
    TaskStatus,
    title_for_level,
)
from lib.utils.postgres_session_decorator import with_postgres_session

DISENGAGED_INACTIVE_DAYS = 3
_DISENGAGED_PREVIEW = 12  # rows shown in the overview panel
_MOVERS_PREVIEW = 5


class CPGamificationService:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    def _panel_ids(
        self,
        care_provider_id: UUID,
        health_facility_id: Optional[UUID],
        is_admin: bool,
    ) -> Select:
        """SELECT of the patient_ids in this actor's panel — evaluated in SQL,
        never materialized in Python. Must mirror the patient-list scope, or
        gamification and the roster disagree on who's in the panel."""
        if is_admin and health_facility_id:
            return select(Patient.patient_id).where(
                Patient.health_facility_id == health_facility_id
            )
        if is_admin:
            return select(Patient.patient_id)
        return select(patient_care_provider_association.c.patient_id).where(
            patient_care_provider_association.c.care_provider_id == care_provider_id
        )

    async def _scalar(self, session: AsyncSession, stmt) -> int:
        return (await session.execute(stmt)).scalar() or 0

    def _summary(self, row, *, is_disengaged: bool, tasks: int = 0) -> PatientEngagementSummary:
        level = row.level or 1
        return PatientEngagementSummary(
            patient_id=str(row.patient_id),
            patient_name=row.first_name,
            level=level,
            title=title_for_level(level),
            total_xp=row.total_xp or 0,
            current_streak=row.current_streak or 0,
            last_active_date=row.last_active_date,
            tasks_completed_this_week=tasks,
            is_disengaged=is_disengaged,
        )

    async def _disengaged_rows(
        self, session: AsyncSession, panel: Select, cutoff, limit: int
    ) -> List[PatientEngagementSummary]:
        rows = (
            await session.execute(
                select(
                    Patient.patient_id,
                    Patient.first_name,
                    PlayerProfile.level,
                    PlayerProfile.current_streak,
                    PlayerProfile.total_xp,
                    PlayerProfile.last_active_date,
                )
                .outerjoin(PlayerProfile, PlayerProfile.patient_id == Patient.patient_id)
                .where(
                    Patient.patient_id.in_(panel),
                    or_(
                        PlayerProfile.last_active_date.is_(None),
                        PlayerProfile.last_active_date < cutoff,
                    ),
                )
                .order_by(PlayerProfile.last_active_date.asc().nulls_first())
                .limit(limit)
            )
        ).all()
        return [self._summary(r, is_disengaged=True) for r in rows]

    @with_postgres_session
    async def get_overview(
        self,
        care_provider_id: UUID,
        *,
        health_facility_id: Optional[UUID] = None,
        is_admin: bool = False,
        postgres_session: AsyncSession,
    ) -> CPGamificationOverview:
        panel = self._panel_ids(care_provider_id, health_facility_id, is_admin)

        total = await self._scalar(
            postgres_session, select(func.count()).select_from(panel.subquery())
        )
        if total == 0:
            return CPGamificationOverview(
                total_patients=0, active_patients=0, disengaged_patients=0
            )

        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        cutoff = today - timedelta(days=DISENGAGED_INACTIVE_DAYS)

        active = await self._scalar(
            postgres_session,
            select(func.count()).select_from(PlayerProfile).where(
                PlayerProfile.patient_id.in_(panel),
                PlayerProfile.last_active_date >= cutoff,
            ),
        )
        sum_streak = await self._scalar(
            postgres_session,
            select(func.coalesce(func.sum(PlayerProfile.current_streak), 0)).where(
                PlayerProfile.patient_id.in_(panel)
            ),
        )
        completed = await self._scalar(
            postgres_session,
            select(func.count()).select_from(DailyTask).where(
                DailyTask.patient_id.in_(panel),
                DailyTask.task_date >= week_start,
                DailyTask.status == TaskStatus.COMPLETED.value,
            ),
        )
        total_tasks = await self._scalar(
            postgres_session,
            select(func.count()).select_from(DailyTask).where(
                DailyTask.patient_id.in_(panel),
                DailyTask.task_date >= week_start,
            ),
        )

        disengaged = await self._disengaged_rows(
            postgres_session, panel, cutoff, _DISENGAGED_PREVIEW
        )
        mover_rows = (
            await postgres_session.execute(
                select(
                    Patient.patient_id,
                    Patient.first_name,
                    PlayerProfile.level,
                    PlayerProfile.current_streak,
                    PlayerProfile.total_xp,
                    PlayerProfile.last_active_date,
                    func.count(DailyTask.task_id).label("cnt"),
                )
                .join(
                    DailyTask,
                    and_(
                        DailyTask.patient_id == Patient.patient_id,
                        DailyTask.task_date >= week_start,
                        DailyTask.status == TaskStatus.COMPLETED.value,
                    ),
                )
                .outerjoin(PlayerProfile, PlayerProfile.patient_id == Patient.patient_id)
                .where(Patient.patient_id.in_(panel))
                .group_by(
                    Patient.patient_id,
                    Patient.first_name,
                    PlayerProfile.level,
                    PlayerProfile.current_streak,
                    PlayerProfile.total_xp,
                    PlayerProfile.last_active_date,
                )
                .order_by(func.count(DailyTask.task_id).desc())
                .limit(_MOVERS_PREVIEW)
            )
        ).all()
        movers = [self._summary(r, is_disengaged=False, tasks=r.cnt) for r in mover_rows]

        return CPGamificationOverview(
            total_patients=total,
            active_patients=active,
            disengaged_patients=total - active,
            avg_streak=round(sum_streak / total, 1),
            task_completion_pct=(
                round(completed / total_tasks * 100, 1) if total_tasks else None
            ),
            disengaged=disengaged,
            top_movers=movers,
        )

    @with_postgres_session
    async def get_leaderboard(
        self,
        care_provider_id: UUID,
        *,
        metric: LeaderboardMetric = "streak",
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None,
        health_facility_id: Optional[UUID] = None,
        is_admin: bool = False,
        postgres_session: AsyncSession,
    ) -> CPLeaderboardResponse:
        """Ranked, paginated, searchable panel leaderboard — ordering and paging
        happen in SQL so the whole panel never loads into memory."""
        panel = self._panel_ids(care_provider_id, health_facility_id, is_admin)
        order_col = (
            PlayerProfile.total_xp if metric == "xp" else PlayerProfile.current_streak
        )
        value = func.coalesce(order_col, 0)

        conditions = [Patient.patient_id.in_(panel)]
        if search and search.strip():
            full_name = func.concat(Patient.first_name, " ", Patient.last_name)
            conditions += [full_name.ilike(f"%{term}%") for term in search.split()]

        total = await self._scalar(
            postgres_session,
            select(func.count()).select_from(Patient).where(*conditions),
        )
        rows = (
            await postgres_session.execute(
                select(
                    Patient.patient_id,
                    Patient.first_name,
                    func.coalesce(PlayerProfile.level, 1).label("level"),
                    func.coalesce(PlayerProfile.total_xp, 0).label("xp"),
                    func.coalesce(PlayerProfile.current_streak, 0).label("streak"),
                )
                .outerjoin(PlayerProfile, PlayerProfile.patient_id == Patient.patient_id)
                .where(*conditions)
                .order_by(value.desc(), Patient.patient_id)
                .limit(limit)
                .offset(offset)
            )
        ).all()

        entries = [
            CPLeaderboardEntry(
                rank=offset + i + 1,
                patient_id=str(r.patient_id),
                patient_name=r.first_name,
                level=r.level,
                title=title_for_level(r.level),
                value=float(r.xp if metric == "xp" else r.streak),
            )
            for i, r in enumerate(rows)
        ]
        return CPLeaderboardResponse(metric=metric, total=total, entries=entries)

    @with_postgres_session
    async def get_disengaged_patients(
        self,
        care_provider_id: UUID,
        *,
        limit: int = 100,
        health_facility_id: Optional[UUID] = None,
        is_admin: bool = False,
        postgres_session: AsyncSession,
    ) -> List[PatientEngagementSummary]:
        panel = self._panel_ids(care_provider_id, health_facility_id, is_admin)
        cutoff = date.today() - timedelta(days=DISENGAGED_INACTIVE_DAYS)
        return await self._disengaged_rows(postgres_session, panel, cutoff, limit)

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
