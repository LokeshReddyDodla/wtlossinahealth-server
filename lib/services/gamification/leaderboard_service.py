"""Leaderboard computation and querying."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import (
    Challenge,
    ChallengeParticipant,
    DailyTask,
    GroupMember,
    LeaderboardEntry,
    PlayerProfile,
    XPLedgerEntry,
)
from lib.models.patient import Patient
from lib.schemas.gamification import (
    LeaderboardEntryResponse,
    LeaderboardResponse,
    TaskStatus,
    title_for_level,
)
from lib.utils.postgres_session_decorator import with_postgres_session


class LeaderboardService:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    @with_postgres_session
    async def get_leaderboard(
        self,
        board_type: str,
        board_scope: str,
        patient_id: UUID,
        *,
        scope_id: Optional[UUID] = None,
        limit: int = 50,
        postgres_session: AsyncSession,
    ) -> LeaderboardResponse:
        today = datetime.utcnow().date()
        if board_type.startswith("weekly"):
            period_start = today - timedelta(days=today.weekday())
            period_end = period_start + timedelta(days=6)
        elif board_type.startswith("monthly"):
            period_start = today.replace(day=1)
            next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            period_end = next_month - timedelta(days=1)
        else:
            # streak and other non-periodic boards use today as period_start
            period_start = today
            period_end = today

        result = await postgres_session.execute(
            select(LeaderboardEntry)
            .where(
                LeaderboardEntry.board_type == board_type,
                LeaderboardEntry.board_scope == board_scope,
                LeaderboardEntry.scope_id == scope_id if scope_id else LeaderboardEntry.scope_id.is_(None),
                LeaderboardEntry.period_start == period_start,
            )
            .order_by(LeaderboardEntry.rank)
            .limit(limit)
        )
        entries = result.scalars().all()

        visibility_result = await postgres_session.execute(
            select(
                PlayerProfile.patient_id,
                PlayerProfile.leaderboard_visibility,
            ).where(
                PlayerProfile.patient_id.in_([entry.patient_id for entry in entries])
            )
        )
        visibility_map = {
            row.patient_id: row.leaderboard_visibility
            for row in visibility_result.all()
        }

        # Batch-load names and levels (avoids N+1)
        entry_pids = [e.patient_id for e in entries]
        names_result = await postgres_session.execute(
            select(Patient.patient_id, Patient.first_name).where(
                Patient.patient_id.in_(entry_pids)
            )
        )
        names_map = {r.patient_id: r.first_name for r in names_result.all()}

        levels_result = await postgres_session.execute(
            select(PlayerProfile.patient_id, PlayerProfile.level).where(
                PlayerProfile.patient_id.in_(entry_pids)
            )
        )
        levels_map = {r.patient_id: r.level for r in levels_result.all()}

        entry_responses = []
        for e in entries:
            name = names_map.get(e.patient_id)
            level = levels_map.get(e.patient_id, 1)
            visible = self._is_identity_visible(
                viewer_id=patient_id,
                subject_id=e.patient_id,
                visibility=visibility_map.get(e.patient_id, "group_only"),
                board_scope=board_scope,
            )

            entry_responses.append(
                LeaderboardEntryResponse(
                    rank=e.rank,
                    patient_id=(
                        str(e.patient_id)
                        if visible
                        else f"anonymous:{e.rank}"
                    ),
                    patient_name=name if visible else "Anonymous",
                    metric_value=e.metric_value,
                    level=level,
                    title=title_for_level(level),
                )
            )

        # Find my rank
        my_rank = None
        for e in entries:
            if e.patient_id == patient_id:
                my_rank = e.rank
                break

        return LeaderboardResponse(
            board_type=board_type,
            board_scope=board_scope,
            period_start=period_start,
            period_end=period_end,
            entries=entry_responses,
            my_rank=my_rank,
        )

    @with_postgres_session
    async def refresh_weekly_xp_board(
        self,
        *,
        scope: str = "global",
        scope_id: Optional[UUID] = None,
        postgres_session: AsyncSession,
    ) -> None:
        """Recompute weekly XP leaderboard."""
        today = datetime.utcnow().date()
        period_start = today - timedelta(days=today.weekday())
        period_end = period_start + timedelta(days=6)
        start_dt = datetime.combine(period_start, datetime.min.time())

        # Delete old entries for this period
        await postgres_session.execute(
            delete(LeaderboardEntry).where(
                LeaderboardEntry.board_type == "weekly_xp",
                LeaderboardEntry.board_scope == scope,
                LeaderboardEntry.scope_id == scope_id if scope_id else LeaderboardEntry.scope_id.is_(None),
                LeaderboardEntry.period_start == period_start,
            )
        )

        patient_ids = await self._scope_patient_ids(scope, scope_id, postgres_session)

        # Compute rankings
        base_query = (
            select(
                XPLedgerEntry.patient_id,
                func.sum(XPLedgerEntry.xp_amount).label("total"),
            )
            .where(
                XPLedgerEntry.created_at >= start_dt,
                XPLedgerEntry.xp_amount > 0,
            )
            .group_by(XPLedgerEntry.patient_id)
            .order_by(func.sum(XPLedgerEntry.xp_amount).desc())
            .limit(100)
        )
        if patient_ids is not None:
            if not patient_ids:
                await postgres_session.commit()
                return
            base_query = base_query.where(
                XPLedgerEntry.patient_id.in_(patient_ids)
            )

        result = await postgres_session.execute(base_query)
        rows = result.all()

        now = datetime.now().replace(tzinfo=None)
        for rank, row in enumerate(rows, 1):
            entry = LeaderboardEntry(
                board_type="weekly_xp",
                board_scope=scope,
                scope_id=scope_id,
                patient_id=row.patient_id,
                rank=rank,
                metric_value=float(row.total),
                period_start=period_start,
                period_end=period_end,
                computed_at=now,
            )
            postgres_session.add(entry)

        await postgres_session.commit()

    @with_postgres_session
    async def refresh_monthly_xp_board(
        self,
        *,
        scope: str = "global",
        scope_id: Optional[UUID] = None,
        postgres_session: AsyncSession,
    ) -> None:
        today = datetime.utcnow().date()
        period_start = today.replace(day=1)
        next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        period_end = next_month - timedelta(days=1)
        start_dt = datetime.combine(period_start, datetime.min.time())

        await postgres_session.execute(
            delete(LeaderboardEntry).where(
                LeaderboardEntry.board_type == "monthly_xp",
                LeaderboardEntry.board_scope == scope,
                LeaderboardEntry.scope_id == scope_id if scope_id else LeaderboardEntry.scope_id.is_(None),
                LeaderboardEntry.period_start == period_start,
            )
        )

        patient_ids = await self._scope_patient_ids(scope, scope_id, postgres_session)
        query = (
            select(
                XPLedgerEntry.patient_id,
                func.sum(XPLedgerEntry.xp_amount).label("total"),
            )
            .where(
                XPLedgerEntry.created_at >= start_dt,
                XPLedgerEntry.xp_amount > 0,
            )
            .group_by(XPLedgerEntry.patient_id)
            .order_by(func.sum(XPLedgerEntry.xp_amount).desc())
            .limit(100)
        )
        if patient_ids is not None:
            if not patient_ids:
                await postgres_session.commit()
                return
            query = query.where(XPLedgerEntry.patient_id.in_(patient_ids))

        rows = (await postgres_session.execute(query)).all()
        now = datetime.now().replace(tzinfo=None)
        for rank, row in enumerate(rows, 1):
            postgres_session.add(
                LeaderboardEntry(
                    board_type="monthly_xp",
                    board_scope=scope,
                    scope_id=scope_id,
                    patient_id=row.patient_id,
                    rank=rank,
                    metric_value=float(row.total),
                    period_start=period_start,
                    period_end=period_end,
                    computed_at=now,
                )
            )

        await postgres_session.commit()

    @with_postgres_session
    async def refresh_weekly_steps_board(
        self,
        *,
        scope: str = "global",
        scope_id: Optional[UUID] = None,
        postgres_session: AsyncSession,
    ) -> None:
        today = datetime.utcnow().date()
        period_start = today - timedelta(days=today.weekday())
        period_end = period_start + timedelta(days=6)

        await postgres_session.execute(
            delete(LeaderboardEntry).where(
                LeaderboardEntry.board_type == "weekly_steps",
                LeaderboardEntry.board_scope == scope,
                LeaderboardEntry.scope_id == scope_id if scope_id else LeaderboardEntry.scope_id.is_(None),
                LeaderboardEntry.period_start == period_start,
            )
        )

        patient_ids = await self._scope_patient_ids(scope, scope_id, postgres_session)
        query = (
            select(
                DailyTask.patient_id,
                func.sum(func.coalesce(DailyTask.current_value, 0)).label("total"),
            )
            .where(
                DailyTask.task_type == "HIT_STEP_GOAL",
                DailyTask.task_date >= period_start,
                DailyTask.task_date <= period_end,
            )
            .group_by(DailyTask.patient_id)
            .order_by(func.sum(func.coalesce(DailyTask.current_value, 0)).desc())
            .limit(100)
        )
        if patient_ids is not None:
            if not patient_ids:
                await postgres_session.commit()
                return
            query = query.where(DailyTask.patient_id.in_(patient_ids))

        rows = (await postgres_session.execute(query)).all()
        now = datetime.now().replace(tzinfo=None)
        for rank, row in enumerate(rows, 1):
            postgres_session.add(
                LeaderboardEntry(
                    board_type="weekly_steps",
                    board_scope=scope,
                    scope_id=scope_id,
                    patient_id=row.patient_id,
                    rank=rank,
                    metric_value=float(row.total or 0),
                    period_start=period_start,
                    period_end=period_end,
                    computed_at=now,
                )
            )
        await postgres_session.commit()

    @with_postgres_session
    async def refresh_streak_board(
        self,
        *,
        scope: str = "global",
        scope_id: Optional[UUID] = None,
        postgres_session: AsyncSession,
    ) -> None:
        """Recompute streak leaderboard."""
        today = datetime.utcnow().date()
        period_start = today
        period_end = today

        await postgres_session.execute(
            delete(LeaderboardEntry).where(
                LeaderboardEntry.board_type == "streak",
                LeaderboardEntry.board_scope == scope,
                LeaderboardEntry.scope_id == scope_id if scope_id else LeaderboardEntry.scope_id.is_(None),
                LeaderboardEntry.period_start == period_start,
            )
        )

        patient_ids = await self._scope_patient_ids(scope, scope_id, postgres_session)

        query = (
            select(PlayerProfile.patient_id, PlayerProfile.current_streak)
            .where(PlayerProfile.current_streak > 0)
            .order_by(PlayerProfile.current_streak.desc())
            .limit(100)
        )
        if patient_ids is not None:
            if not patient_ids:
                await postgres_session.commit()
                return
            query = query.where(PlayerProfile.patient_id.in_(patient_ids))

        result = await postgres_session.execute(query)
        rows = result.all()

        now = datetime.now().replace(tzinfo=None)
        for rank, row in enumerate(rows, 1):
            entry = LeaderboardEntry(
                board_type="streak",
                board_scope=scope,
                scope_id=scope_id,
                patient_id=row.patient_id,
                rank=rank,
                metric_value=float(row.current_streak),
                period_start=period_start,
                period_end=period_end,
                computed_at=now,
            )
            postgres_session.add(entry)

        await postgres_session.commit()

    @with_postgres_session
    async def refresh_challenge_board(
        self,
        challenge_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        challenge = await postgres_session.execute(
            select(Challenge).where(Challenge.challenge_id == challenge_id)
        )
        challenge_obj = challenge.scalars().first()
        if not challenge_obj:
            return

        await postgres_session.execute(
            delete(LeaderboardEntry).where(
                LeaderboardEntry.board_type == "challenge",
                LeaderboardEntry.board_scope == "challenge",
                LeaderboardEntry.scope_id == challenge_id,
            )
        )

        rows = await postgres_session.execute(
            select(ChallengeParticipant)
            .where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.participant_type == "patient",
                ChallengeParticipant.status.in_(["active", "completed"]),
            )
            .order_by(ChallengeParticipant.current_value.desc())
        )
        participants = rows.scalars().all()
        now = datetime.now().replace(tzinfo=None)
        for rank, participant in enumerate(participants, 1):
            postgres_session.add(
                LeaderboardEntry(
                    board_type="challenge",
                    board_scope="challenge",
                    scope_id=challenge_id,
                    patient_id=participant.participant_id,
                    rank=rank,
                    metric_value=participant.current_value,
                    period_start=challenge_obj.start_date,
                    period_end=challenge_obj.end_date,
                    computed_at=now,
                )
            )

        await postgres_session.commit()

    @with_postgres_session
    async def refresh_all_boards(
        self, *, postgres_session: AsyncSession
    ) -> None:
        await self.refresh_weekly_xp_board(postgres_session=postgres_session)
        await self.refresh_monthly_xp_board(postgres_session=postgres_session)
        await self.refresh_weekly_steps_board(postgres_session=postgres_session)
        await self.refresh_streak_board(postgres_session=postgres_session)

        group_ids = await postgres_session.execute(
            select(GroupMember.group_id).where(GroupMember.is_active == True).distinct()
        )
        for group_id in group_ids.scalars().all():
            await self.refresh_weekly_xp_board(
                scope="group",
                scope_id=group_id,
                postgres_session=postgres_session,
            )
            await self.refresh_monthly_xp_board(
                scope="group",
                scope_id=group_id,
                postgres_session=postgres_session,
            )
            await self.refresh_weekly_steps_board(
                scope="group",
                scope_id=group_id,
                postgres_session=postgres_session,
            )
            await self.refresh_streak_board(
                scope="group",
                scope_id=group_id,
                postgres_session=postgres_session,
            )

        facility_ids = await postgres_session.execute(
            select(Patient.health_facility_id)
            .where(Patient.health_facility_id.is_not(None))
            .distinct()
        )
        for facility_id in facility_ids.scalars().all():
            await self.refresh_weekly_xp_board(
                scope="facility",
                scope_id=facility_id,
                postgres_session=postgres_session,
            )
            await self.refresh_monthly_xp_board(
                scope="facility",
                scope_id=facility_id,
                postgres_session=postgres_session,
            )
            await self.refresh_weekly_steps_board(
                scope="facility",
                scope_id=facility_id,
                postgres_session=postgres_session,
            )
            await self.refresh_streak_board(
                scope="facility",
                scope_id=facility_id,
                postgres_session=postgres_session,
            )

        challenge_ids = await postgres_session.execute(
            select(Challenge.challenge_id).where(Challenge.is_active == True)
        )
        for challenge_id in challenge_ids.scalars().all():
            await self.refresh_challenge_board(
                challenge_id,
                postgres_session=postgres_session,
            )

    @with_postgres_session
    async def cleanup_old_entries(
        self, days: int = 90, *, postgres_session: AsyncSession
    ) -> int:
        cutoff = date.today() - timedelta(days=days)
        result = await postgres_session.execute(
            delete(LeaderboardEntry).where(
                LeaderboardEntry.period_end < cutoff
            )
        )
        await postgres_session.commit()
        return result.rowcount or 0

    async def _scope_patient_ids(
        self,
        scope: str,
        scope_id: Optional[UUID],
        session: AsyncSession,
    ) -> Optional[List[UUID]]:
        if scope == "global":
            return None
        if scope == "group" and scope_id:
            result = await session.execute(
                select(GroupMember.patient_id).where(
                    GroupMember.group_id == scope_id,
                    GroupMember.is_active == True,
                )
            )
            return list(result.scalars().all())
        if scope == "facility" and scope_id:
            result = await session.execute(
                select(Patient.patient_id).where(
                    Patient.health_facility_id == scope_id
                )
            )
            return list(result.scalars().all())
        if scope == "challenge" and scope_id:
            result = await session.execute(
                select(ChallengeParticipant.participant_id).where(
                    ChallengeParticipant.challenge_id == scope_id,
                    ChallengeParticipant.participant_type == "patient",
                    ChallengeParticipant.status.in_(["active", "completed"]),
                )
            )
            return list(result.scalars().all())
        return []

    def _is_identity_visible(
        self,
        *,
        viewer_id: UUID,
        subject_id: UUID,
        visibility: str,
        board_scope: str,
    ) -> bool:
        if viewer_id == subject_id:
            return True
        if visibility == "public":
            return True
        if visibility == "group_only":
            return board_scope in {"group", "challenge"}
        return False
