"""Unified check-in history — merges sleep, mood, symptoms with gamification data."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import cast, Date, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import DailyTask, PlayerProfile, XPLedgerEntry
from lib.models.mood_entry import MoodEntry
from lib.models.sleep_checkin import SleepCheckin
from lib.models.symptom_entry import SymptomEntry
from lib.schemas.checkin_history import (
    CheckinDay,
    CheckinHistoryResponse,
    CheckinInsight,
    CheckinSummary,
    MoodSnapshot,
    SleepSnapshot,
    SymptomItem,
    SymptomSnapshot,
    WeeklyRecap,
)
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)


class CheckinHistoryService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        insight_tracker: Any,
    ):
        self.postgres_store = postgres_store
        self.insight_tracker = insight_tracker

    @with_postgres_session
    async def get_history(
        self,
        patient_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 30,
        offset: int = 0,
        *,
        postgres_session: AsyncSession,
    ) -> CheckinHistoryResponse:
        today = date.today()
        end = end_date or today
        start = start_date or (end - timedelta(days=limit - 1))

        # Run all queries in parallel
        (
            sleep_rows,
            mood_rows,
            symptom_rows,
            task_rows,
            xp_rows,
            profile,
            insights,
        ) = await asyncio.gather(
            self._fetch_sleep(postgres_session, patient_id, start, end),
            self._fetch_moods(postgres_session, patient_id, start, end),
            self._fetch_symptoms(postgres_session, patient_id, start, end),
            self._fetch_tasks(postgres_session, patient_id, start, end),
            self._fetch_xp_per_day(postgres_session, patient_id, start, end),
            self._fetch_profile(postgres_session, patient_id),
            self._fetch_insights(patient_id, start, end),
        )

        # Build lookup maps
        sleep_map = {r.checkin_date: r for r in sleep_rows}
        mood_map: dict[date, MoodEntry] = {}
        for m in mood_rows:
            d = m.recorded_at.date() if m.recorded_at else None
            if d and d not in mood_map:
                mood_map[d] = m

        symptom_map: dict[date, list] = defaultdict(list)
        for s in symptom_rows:
            d = s.recorded_at.date() if s.recorded_at else None
            if d:
                symptom_map[d].append(s)

        task_map: dict[date, list] = defaultdict(list)
        for t in task_rows:
            task_map[t.task_date].append(t)

        xp_map: dict[date, int] = dict(xp_rows)

        # Build days
        all_dates = sorted(
            {start + timedelta(days=i) for i in range((end - start).days + 1)},
            reverse=True,
        )
        # Apply pagination
        paginated_dates = all_dates[offset : offset + limit]

        days = []
        for d in paginated_dates:
            sleep = sleep_map.get(d)
            mood = mood_map.get(d)
            symptoms = symptom_map.get(d, [])
            completed_tasks = [
                t.task_type for t in task_map.get(d, [])
            ]

            days.append(
                CheckinDay(
                    date=d,
                    sleep=self._sleep_snapshot(sleep) if sleep else None,
                    mood=self._mood_snapshot(mood) if mood else None,
                    symptoms=[self._symptom_snapshot(s) for s in symptoms],
                    xp_earned=xp_map.get(d, 0),
                    tasks_completed=completed_tasks,
                )
            )

        summary = self._build_summary(
            sleep_rows, mood_rows, symptom_rows, xp_rows, profile
        )
        weekly_recaps = self._build_weekly_recaps(
            all_dates, sleep_map, mood_map, symptom_map, xp_map
        )

        return CheckinHistoryResponse(
            days=days,
            summary=summary,
            insights=[
                CheckinInsight(
                    insight_id=ins.get("insight_id", ""),
                    category=ins.get("category", ""),
                    severity=ins.get("severity", "info"),
                    title=ins.get("title", ""),
                    body=ins.get("message", ""),
                )
                for ins in insights
                if ins.get("insight_id")
            ],
            weekly_recaps=weekly_recaps,
            total=len(all_dates),
        )

    # ── PostgreSQL queries ───────────────────────────────────────────────

    async def _fetch_sleep(
        self, session: AsyncSession, pid: str, start: date, end: date
    ) -> list:
        result = await session.execute(
            select(SleepCheckin)
            .where(
                SleepCheckin.patient_id == pid,
                SleepCheckin.checkin_date >= start,
                SleepCheckin.checkin_date <= end,
            )
            .order_by(SleepCheckin.checkin_date.desc())
        )
        return list(result.scalars().all())

    async def _fetch_moods(
        self, session: AsyncSession, pid: str, start: date, end: date
    ) -> list:
        result = await session.execute(
            select(MoodEntry)
            .where(
                MoodEntry.patient_id == pid,
                cast(MoodEntry.recorded_at, Date) >= start,
                cast(MoodEntry.recorded_at, Date) <= end,
            )
            .order_by(MoodEntry.recorded_at.desc())
        )
        return list(result.scalars().all())

    async def _fetch_symptoms(
        self, session: AsyncSession, pid: str, start: date, end: date
    ) -> list:
        result = await session.execute(
            select(SymptomEntry)
            .where(
                SymptomEntry.patient_id == pid,
                cast(SymptomEntry.recorded_at, Date) >= start,
                cast(SymptomEntry.recorded_at, Date) <= end,
            )
            .options(selectinload(SymptomEntry.items))
            .order_by(SymptomEntry.recorded_at.desc())
        )
        return list(result.scalars().all())

    async def _fetch_tasks(
        self, session: AsyncSession, pid: str, start: date, end: date
    ) -> list:
        result = await session.execute(
            select(DailyTask)
            .where(
                DailyTask.patient_id == pid,
                DailyTask.task_date >= start,
                DailyTask.task_date <= end,
                DailyTask.status == "completed",
            )
        )
        return list(result.scalars().all())

    async def _fetch_xp_per_day(
        self, session: AsyncSession, pid: str, start: date, end: date
    ) -> list[tuple[date, int]]:
        result = await session.execute(
            select(
                cast(XPLedgerEntry.created_at, Date).label("day"),
                func.sum(XPLedgerEntry.xp_amount).label("xp"),
            )
            .where(
                XPLedgerEntry.patient_id == pid,
                cast(XPLedgerEntry.created_at, Date) >= start,
                cast(XPLedgerEntry.created_at, Date) <= end,
            )
            .group_by("day")
        )
        return [(row.day, int(row.xp)) for row in result.all()]

    async def _fetch_profile(
        self, session: AsyncSession, pid: str
    ) -> PlayerProfile | None:
        result = await session.execute(
            select(PlayerProfile).where(PlayerProfile.patient_id == pid)
        )
        return result.scalars().first()

    # ── MongoDB query ────────────────────────────────────────────────────

    async def _fetch_insights(
        self, pid: str, start: date, end: date
    ) -> list[dict]:
        try:
            start_dt = datetime.combine(start, datetime.min.time())
            end_dt = datetime.combine(end, datetime.max.time())
            cursor = self.insight_tracker._collection.find(
                {
                    "patient_id": pid,
                    "insight_id": {"$exists": True},
                    "created_at": {"$gte": start_dt, "$lte": end_dt},
                },
                sort=[("created_at", -1)],
                limit=10,
            )
            return [doc async for doc in cursor]
        except Exception:
            logger.exception("Failed to fetch insights for %s", pid)
            return []

    # ── Snapshot builders ────────────────────────────────────────────────

    @staticmethod
    def _sleep_snapshot(r) -> SleepSnapshot:
        return SleepSnapshot(
            id=str(r.id),
            quality=r.quality,
            hours_slept=r.hours_slept,
            bed_time=r.bed_time,
            wake_time=r.wake_time,
            notes=r.notes,
        )

    @staticmethod
    def _mood_snapshot(r) -> MoodSnapshot:
        return MoodSnapshot(
            id=str(r.id),
            level=r.level,
            emoji=r.emoji,
            tags=r.tags or [],
            notes=r.notes,
            recorded_at=r.recorded_at,
        )

    @staticmethod
    def _symptom_snapshot(r) -> SymptomSnapshot:
        return SymptomSnapshot(
            id=str(r.id),
            symptoms=[
                SymptomItem(
                    symptom_name=item.symptom_name,
                    severity=item.severity,
                    custom_label=item.custom_label,
                )
                for item in (r.items or [])
            ],
            notes=r.notes,
            recorded_at=r.recorded_at,
        )

    # ── Summary ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_summary(
        sleep_rows, mood_rows, symptom_rows, xp_rows, profile
    ) -> CheckinSummary:
        # Days logged = days with any checkin
        sleep_dates = {r.checkin_date for r in sleep_rows}
        mood_dates = {r.recorded_at.date() for r in mood_rows if r.recorded_at}
        symptom_dates = {r.recorded_at.date() for r in symptom_rows if r.recorded_at}
        all_logged_dates = sleep_dates | mood_dates | symptom_dates
        fully_complete = sleep_dates & mood_dates  # has both sleep + mood

        # Sleep averages
        sleep_hours = [r.hours_slept for r in sleep_rows if r.hours_slept]
        sleep_qualities = [r.quality for r in sleep_rows if r.quality]

        # Dominant mood
        mood_counter = Counter(r.emoji for r in mood_rows if r.emoji)
        dominant = mood_counter.most_common(1)
        dominant_mood = dominant[0][0] if dominant else None
        mood_levels = [r.level for r in mood_rows if r.level]

        # Symptoms
        all_symptom_names = []
        for s in symptom_rows:
            for item in (s.items or []):
                all_symptom_names.append(item.symptom_name)
        symptom_counter = Counter(all_symptom_names)
        most_common = symptom_counter.most_common(1)

        # XP
        total_xp = sum(xp for _, xp in xp_rows)

        total_days = max(len(all_logged_dates), 1)

        return CheckinSummary(
            total_days_logged=len(all_logged_dates),
            fully_complete_days=len(fully_complete),
            completion_rate=round(len(fully_complete) / total_days, 2),
            avg_sleep_hours=round(sum(sleep_hours) / len(sleep_hours), 1) if sleep_hours else None,
            avg_sleep_quality=round(sum(sleep_qualities) / len(sleep_qualities), 1) if sleep_qualities else None,
            dominant_mood=dominant_mood,
            dominant_mood_level=round(sum(mood_levels) / len(mood_levels)) if mood_levels else None,
            total_symptoms_logged=len(all_symptom_names),
            most_common_symptom=most_common[0][0] if most_common else None,
            total_xp_earned=total_xp,
            current_streak=profile.current_streak if profile else 0,
            longest_streak=profile.longest_streak if profile else 0,
            level=profile.level if profile else 1,
        )

    # ── Weekly recaps ────────────────────────────────────────────────────

    @staticmethod
    def _build_weekly_recaps(
        all_dates, sleep_map, mood_map, symptom_map, xp_map
    ) -> list[WeeklyRecap]:
        if not all_dates:
            return []

        # Group dates by ISO week
        weeks: dict[tuple[int, int], list[date]] = defaultdict(list)
        for d in all_dates:
            iso = d.isocalendar()
            weeks[(iso[0], iso[1])].append(d)

        recaps = []
        for (year, week_num), dates in sorted(weeks.items()):
            dates_sorted = sorted(dates)
            week_start = dates_sorted[0]
            week_end = dates_sorted[-1]

            sleep_hours = []
            mood_levels = []
            symptom_count = 0
            xp = 0
            days_logged = 0

            for d in dates_sorted:
                has_data = False
                s = sleep_map.get(d)
                if s and s.hours_slept:
                    sleep_hours.append(s.hours_slept)
                    has_data = True
                m = mood_map.get(d)
                if m:
                    mood_levels.append(m.level)
                    has_data = True
                symptom_count += len(symptom_map.get(d, []))
                if symptom_map.get(d):
                    has_data = True
                xp += xp_map.get(d, 0)
                if has_data:
                    days_logged += 1

            recaps.append(
                WeeklyRecap(
                    week_label=f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d')}",
                    dominant_mood_level=round(sum(mood_levels) / len(mood_levels)) if mood_levels else None,
                    avg_sleep_hours=round(sum(sleep_hours) / len(sleep_hours), 1) if sleep_hours else None,
                    symptom_count=symptom_count,
                    completion_rate=round(days_logged / len(dates_sorted), 2) if dates_sorted else 0,
                    xp_earned=xp,
                    days_logged=days_logged,
                    total_days=len(dates_sorted),
                )
            )

        return recaps
