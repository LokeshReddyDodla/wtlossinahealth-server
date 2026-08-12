"""Data access for progress trends.

Three sources, each already the single source of truth for its domain:
ClickHouse vitals summary (labs/vitals), stored daily CGM reports (glucose),
Postgres DailyTask + PlayerProfile (engagement). No new write path.
"""

import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.clickhouse_store import ClickHouseStore
from lib.models.care_intent import CareIntent
from lib.models.care_intent_event import CareIntentEvent
from lib.models.gamification import DailyTask, PlayerProfile

logger = logging.getLogger(__name__)


class ProgressRepository:
    def __init__(self, clickhouse_store: ClickHouseStore):
        self.clickhouse_store = clickhouse_store

    async def vitals_daily(
        self, patient_id: str, start: datetime, end: datetime
    ) -> list[dict]:
        """Daily avg per vital type — rows are {date, type, avg, min, max, count}.
        query_vitals_summary is sync (clickhouse-driver), so run it off the loop."""
        try:
            return await asyncio.to_thread(
                self.clickhouse_store.query_vitals_summary, patient_id, start, end
            )
        except Exception:
            logger.exception("progress vitals query failed")
            return []

    async def task_completion_daily(
        self, pid, start: date, end: date, session: AsyncSession
    ) -> list[tuple[date, float]]:
        """Per-day task completion % over the range."""
        rows = (await session.execute(
            select(
                DailyTask.task_date,
                func.count().label("total"),
                func.sum(case((DailyTask.status == "completed", 1), else_=0)).label("done"),
            )
            .where(
                DailyTask.patient_id == pid,
                DailyTask.task_date >= start,
                DailyTask.task_date <= end,
            )
            .group_by(DailyTask.task_date)
        )).all()
        out: list[tuple[date, float]] = []
        for task_date, total, done in rows:
            if total:
                out.append((task_date, round((done or 0) / total * 100, 1)))
        return out

    async def streak(self, pid, session: AsyncSession) -> tuple[int, int]:
        profile = (await session.execute(
            select(PlayerProfile).where(PlayerProfile.patient_id == pid)
        )).scalar_one_or_none()
        if profile is None:
            return 0, 0
        return profile.current_streak or 0, profile.longest_streak or 0

    async def care_intent_adherence(
        self, pid, start: date, end: date, session: AsyncSession
    ) -> list[dict]:
        """Per active care intent: followed/missed/unclear day-counts over the
        range, plus the most recent barrier note. Daily verdicts are written by
        the monitor's morning scan (one row per intent per day)."""
        intents = (await session.execute(
            select(CareIntent)
            .where(CareIntent.patient_id == pid, CareIntent.status == "active")
            .order_by(CareIntent.created_at)
        )).scalars().all()
        if not intents:
            return []
        ids = [i.care_intent_id for i in intents]

        counts = (await session.execute(
            select(
                CareIntentEvent.care_intent_id,
                CareIntentEvent.status,
                func.count().label("n"),
            )
            .where(
                CareIntentEvent.care_intent_id.in_(ids),
                CareIntentEvent.event_date >= start,
                CareIntentEvent.event_date <= end,
            )
            .group_by(CareIntentEvent.care_intent_id, CareIntentEvent.status)
        )).all()
        tally: dict = {}
        for cid, status, n in counts:
            tally.setdefault(cid, {})[status] = n

        # Most recent barrier note per intent — desc order, first seen wins.
        note_rows = (await session.execute(
            select(CareIntentEvent.care_intent_id, CareIntentEvent.note)
            .where(
                CareIntentEvent.care_intent_id.in_(ids),
                CareIntentEvent.note.isnot(None),
                CareIntentEvent.event_date >= start,
                CareIntentEvent.event_date <= end,
            )
            .order_by(CareIntentEvent.event_date.desc())
        )).all()
        last_note: dict = {}
        for cid, note in note_rows:
            last_note.setdefault(cid, note)

        out: list[dict] = []
        for i in intents:
            t = tally.get(i.care_intent_id, {})
            followed = int(t.get("followed", 0))
            missed = int(t.get("missed", 0))
            decided = followed + missed
            out.append({
                "care_intent_id": str(i.care_intent_id),
                "summary": i.patient_summary,
                "author": i.author_name,
                "followed": followed,
                "missed": missed,
                "unclear": int(t.get("unclear", 0)),
                "rate": round(followed / decided, 2) if decided else None,
                "last_note": last_note.get(i.care_intent_id),
            })
        return out
