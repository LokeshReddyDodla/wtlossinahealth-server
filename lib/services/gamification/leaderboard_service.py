"""Leaderboard computation and querying."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import (
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
        today = date.today()
        if board_type.startswith("weekly"):
            period_start = today - timedelta(days=today.weekday())
            period_end = period_start + timedelta(days=6)
        elif board_type.startswith("monthly"):
            period_start = today.replace(day=1)
            next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            period_end = next_month - timedelta(days=1)
        else:
            period_start = today - timedelta(days=30)
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

        # Enrich with names and levels
        entry_responses = []
        for e in entries:
            name_result = await postgres_session.execute(
                select(Patient.first_name).where(
                    Patient.patient_id == e.patient_id
                )
            )
            name = name_result.scalar()
            profile_result = await postgres_session.execute(
                select(PlayerProfile.level).where(
                    PlayerProfile.patient_id == e.patient_id
                )
            )
            level = profile_result.scalar() or 1

            entry_responses.append(
                LeaderboardEntryResponse(
                    rank=e.rank,
                    patient_id=str(e.patient_id),
                    patient_name=name,
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
        today = date.today()
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

        # Filter by group members if scope is "group"
        if scope == "group" and scope_id:
            member_ids = await postgres_session.execute(
                select(GroupMember.patient_id).where(
                    GroupMember.group_id == scope_id,
                    GroupMember.is_active == True,
                )
            )
            patient_ids = list(member_ids.scalars().all())
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
    async def refresh_streak_board(
        self,
        *,
        scope: str = "global",
        scope_id: Optional[UUID] = None,
        postgres_session: AsyncSession,
    ) -> None:
        """Recompute streak leaderboard."""
        today = date.today()
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

        query = (
            select(PlayerProfile.patient_id, PlayerProfile.current_streak)
            .where(PlayerProfile.current_streak > 0)
            .order_by(PlayerProfile.current_streak.desc())
            .limit(100)
        )

        if scope == "group" and scope_id:
            member_ids = await postgres_session.execute(
                select(GroupMember.patient_id).where(
                    GroupMember.group_id == scope_id,
                    GroupMember.is_active == True,
                )
            )
            patient_ids = list(member_ids.scalars().all())
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
