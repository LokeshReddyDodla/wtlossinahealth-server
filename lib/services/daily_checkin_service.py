"""Service for daily sleep check-ins, mood entries, and symptom entries."""

import logging
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import status
from sqlalchemy import Date, func, cast
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.mood_entry import MoodEntry
from lib.models.sleep_checkin import SleepCheckin
from lib.models.symptom_entry import SymptomEntry, SymptomEntryItem
from lib.schemas.daily_checkin import MoodEntryInput, SleepCheckinInput, SymptomEntryInput
from lib.services.vector.checkin import CheckinVectorService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)


class DailyCheckinService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        checkin_vector_service: CheckinVectorService,
    ):
        self.postgres_store = postgres_store
        self.checkin_vector_service = checkin_vector_service

    # ── Sleep ──────────────────────────────────────────────────────────────

    @with_postgres_session
    async def upsert_sleep(
        self,
        patient_id: str,
        data: SleepCheckinInput,
        *,
        postgres_session: AsyncSession,
    ) -> SleepCheckin:
        checkin_date = data.checkin_date
        try:
            result = await postgres_session.execute(
                select(SleepCheckin).where(
                    SleepCheckin.patient_id == patient_id,
                    SleepCheckin.checkin_date == checkin_date,
                )
            )
            existing = result.scalars().first()

            if existing:
                existing.quality = data.quality
                existing.hours_slept = data.hours_slept
                existing.bed_time = data.bed_time
                existing.wake_time = data.wake_time
                existing.notes = data.notes
                await postgres_session.commit()
                await postgres_session.refresh(existing)
                record = existing
            else:
                record = SleepCheckin(
                    patient_id=patient_id,
                    checkin_date=checkin_date,
                    quality=data.quality,
                    hours_slept=data.hours_slept,
                    bed_time=data.bed_time,
                    wake_time=data.wake_time,
                    notes=data.notes,
                )
                postgres_session.add(record)
                await postgres_session.commit()
                await postgres_session.refresh(record)

            # Vectorize (fire-and-forget logging on error)
            try:
                await self.checkin_vector_service.upsert_sleep_vector(
                    patient_id=patient_id,
                    sleep_data={
                        "checkin_date": str(checkin_date),
                        "quality": data.quality,
                        "hours_slept": data.hours_slept,
                        "bed_time": data.bed_time,
                        "wake_time": data.wake_time,
                        "notes": data.notes,
                    },
                    patient_age=0,
                    patient_gender="unknown",
                )
            except Exception as e:
                logger.error(f"Failed to vectorize sleep for {patient_id}: {e}")

            # Gamification hook (fire-and-forget)
            try:
                from lib.core.container import container
                from lib.services.gamification.event_handler import GamificationEventHandler
                handler = container.resolve(GamificationEventHandler)
                await handler.on_sleep_logged(UUID(patient_id))
            except Exception:
                pass

            return record

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database error",
                detail=str(e),
            )

    @with_postgres_session
    async def get_sleep_history(
        self,
        patient_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 20,
        offset: int = 0,
        *,
        postgres_session: AsyncSession,
    ) -> Tuple[List[SleepCheckin], int]:
        try:
            query = select(SleepCheckin).where(SleepCheckin.patient_id == patient_id)
            count_query = select(func.count(SleepCheckin.id)).where(SleepCheckin.patient_id == patient_id)

            if start_date:
                query = query.where(SleepCheckin.checkin_date >= start_date)
                count_query = count_query.where(SleepCheckin.checkin_date >= start_date)
            if end_date:
                query = query.where(SleepCheckin.checkin_date <= end_date)
                count_query = count_query.where(SleepCheckin.checkin_date <= end_date)

            total = (await postgres_session.execute(count_query)).scalar() or 0

            query = query.order_by(SleepCheckin.checkin_date.desc()).limit(limit).offset(offset)
            result = await postgres_session.execute(query)
            return list(result.scalars().all()), total

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database error",
                detail=str(e),
            )

    @with_postgres_session
    async def get_sleep_trends(
        self,
        patient_id: str,
        period: str = "weekly",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        *,
        postgres_session: AsyncSession,
    ) -> Dict[str, Any]:
        try:
            if not start_date:
                start_date = date.today() - timedelta(days=90)
            if not end_date:
                end_date = date.today()

            trunc = "week" if period == "weekly" else "month"

            stmt = (
                select(
                    func.date_trunc(trunc, SleepCheckin.checkin_date).label("period"),
                    func.avg(SleepCheckin.quality).label("avg_quality"),
                    func.avg(SleepCheckin.hours_slept).label("avg_hours"),
                    func.count(SleepCheckin.id).label("count"),
                )
                .where(
                    SleepCheckin.patient_id == patient_id,
                    SleepCheckin.checkin_date >= start_date,
                    SleepCheckin.checkin_date <= end_date,
                )
                .group_by("period")
                .order_by("period")
            )
            result = await postgres_session.execute(stmt)
            rows = result.all()

            periods = [
                {
                    "label": row.period.strftime("%Y-%m-%d") if row.period else "",
                    "avg_quality": round(float(row.avg_quality), 1),
                    "avg_hours": round(float(row.avg_hours), 1),
                    "count": row.count,
                }
                for row in rows
            ]

            current_streak, longest_streak = await self._compute_sleep_streaks(
                patient_id, postgres_session=postgres_session,
            )

            return {
                "periods": periods,
                "current_streak": current_streak,
                "longest_streak": longest_streak,
            }

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database error",
                detail=str(e),
            )

    async def _compute_sleep_streaks(
        self, patient_id: str, *, postgres_session: AsyncSession,
    ) -> Tuple[int, int]:
        result = await postgres_session.execute(
            select(SleepCheckin.checkin_date)
            .where(SleepCheckin.patient_id == patient_id)
            .order_by(SleepCheckin.checkin_date.desc())
        )
        dates = sorted({row[0] for row in result.all()})
        if not dates:
            return 0, 0

        # Longest streak
        longest = 1
        current = 1
        for i in range(1, len(dates)):
            if (dates[i] - dates[i - 1]).days == 1:
                current += 1
                longest = max(longest, current)
            else:
                current = 1

        # Current streak (from today backwards)
        today = date.today()
        current_streak = 0
        for d in reversed(dates):
            expected = today - timedelta(days=current_streak)
            if d == expected:
                current_streak += 1
            else:
                break

        return current_streak, longest

    # ── Mood ───────────────────────────────────────────────────────────────

    @with_postgres_session
    async def add_mood(
        self,
        patient_id: str,
        data: MoodEntryInput,
        *,
        postgres_session: AsyncSession,
    ) -> MoodEntry:
        recorded_at = data.recorded_at.replace(tzinfo=None) if data.recorded_at.tzinfo else data.recorded_at
        try:
            record = MoodEntry(
                patient_id=patient_id,
                level=data.level,
                emoji=data.emoji,
                tags=data.tags,
                notes=data.notes,
                recorded_at=recorded_at,
            )
            postgres_session.add(record)
            await postgres_session.commit()
            await postgres_session.refresh(record)

            # Vectorize
            try:
                await self.checkin_vector_service.upsert_mood_vector(
                    patient_id=patient_id,
                    mood_entry_id=str(record.id),
                    mood_data={
                        "level": data.level,
                        "emoji": data.emoji,
                        "tags": data.tags,
                        "notes": data.notes,
                        "recorded_at": recorded_at,
                    },
                    patient_age=0,
                    patient_gender="unknown",
                )
            except Exception as e:
                logger.error(f"Failed to vectorize mood for {patient_id}: {e}")

            # Gamification hook (fire-and-forget)
            try:
                from lib.core.container import container
                from lib.services.gamification.event_handler import GamificationEventHandler
                handler = container.resolve(GamificationEventHandler)
                await handler.on_mood_logged(UUID(patient_id))
            except Exception:
                pass

            return record

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database error",
                detail=str(e),
            )

    @with_postgres_session
    async def get_mood_history(
        self,
        patient_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 20,
        offset: int = 0,
        *,
        postgres_session: AsyncSession,
    ) -> Tuple[List[MoodEntry], int]:
        try:
            query = select(MoodEntry).where(MoodEntry.patient_id == patient_id)
            count_query = select(func.count(MoodEntry.id)).where(MoodEntry.patient_id == patient_id)

            if start_date:
                query = query.where(MoodEntry.recorded_at >= start_date)
                count_query = count_query.where(MoodEntry.recorded_at >= start_date)
            if end_date:
                query = query.where(MoodEntry.recorded_at <= end_date)
                count_query = count_query.where(MoodEntry.recorded_at <= end_date)

            total = (await postgres_session.execute(count_query)).scalar() or 0

            query = query.order_by(MoodEntry.recorded_at.desc()).limit(limit).offset(offset)
            result = await postgres_session.execute(query)
            return list(result.scalars().all()), total

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database error",
                detail=str(e),
            )

    @with_postgres_session
    async def get_mood_trends(
        self,
        patient_id: str,
        period: str = "weekly",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        *,
        postgres_session: AsyncSession,
    ) -> Dict[str, Any]:
        try:
            if not start_date:
                start_date = date.today() - timedelta(days=90)
            if not end_date:
                end_date = date.today()

            trunc = "week" if period == "weekly" else "month"

            # Averages per period
            stmt = (
                select(
                    func.date_trunc(trunc, MoodEntry.recorded_at).label("period"),
                    func.avg(MoodEntry.level).label("avg_level"),
                    func.count(MoodEntry.id).label("count"),
                )
                .where(
                    MoodEntry.patient_id == patient_id,
                    cast(MoodEntry.recorded_at, Date) >= start_date,
                    cast(MoodEntry.recorded_at, Date) <= end_date,
                )
                .group_by("period")
                .order_by("period")
            )
            result = await postgres_session.execute(stmt)
            rows = result.all()

            # Top tags across entire period
            tag_stmt = (
                select(func.unnest(MoodEntry.tags).label("tag"))
                .where(
                    MoodEntry.patient_id == patient_id,
                    cast(MoodEntry.recorded_at, Date) >= start_date,
                    cast(MoodEntry.recorded_at, Date) <= end_date,
                )
            )
            tag_result = await postgres_session.execute(tag_stmt)
            tag_counts = Counter(row[0] for row in tag_result.all())
            top_tags = [tag for tag, _ in tag_counts.most_common(5)]

            periods = [
                {
                    "label": row.period.strftime("%Y-%m-%d") if row.period else "",
                    "avg_level": round(float(row.avg_level), 1),
                    "count": row.count,
                    "top_tags": top_tags,
                }
                for row in rows
            ]

            current_streak, longest_streak = await self._compute_mood_streaks(
                patient_id, postgres_session=postgres_session,
            )

            return {
                "periods": periods,
                "current_streak": current_streak,
                "longest_streak": longest_streak,
            }

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database error",
                detail=str(e),
            )

    async def _compute_mood_streaks(
        self, patient_id: str, *, postgres_session: AsyncSession,
    ) -> Tuple[int, int]:
        result = await postgres_session.execute(
            select(cast(MoodEntry.recorded_at, Date).label("day"))
            .where(MoodEntry.patient_id == patient_id)
            .distinct()
            .order_by("day")
        )
        dates = sorted({row[0] for row in result.all()})
        if not dates:
            return 0, 0

        longest = 1
        current = 1
        for i in range(1, len(dates)):
            if (dates[i] - dates[i - 1]).days == 1:
                current += 1
                longest = max(longest, current)
            else:
                current = 1

        today = date.today()
        current_streak = 0
        for d in reversed(dates):
            expected = today - timedelta(days=current_streak)
            if d == expected:
                current_streak += 1
            else:
                break

        return current_streak, longest

    # ── Symptoms ──────────────────────────────────────────────────────────

    @with_postgres_session
    async def add_symptoms(
        self,
        patient_id: str,
        data: SymptomEntryInput,
        *,
        postgres_session: AsyncSession,
    ) -> SymptomEntry:
        recorded_at = data.recorded_at.replace(tzinfo=None) if data.recorded_at.tzinfo else data.recorded_at
        try:
            record = SymptomEntry(
                patient_id=patient_id,
                recorded_at=recorded_at,
                notes=data.notes,
            )
            for item in data.symptoms:
                record.items.append(
                    SymptomEntryItem(
                        symptom_name=item.symptom_name,
                        severity=item.severity,
                        custom_label=item.custom_label,
                    )
                )
            postgres_session.add(record)
            await postgres_session.commit()
            await postgres_session.refresh(record, ["items"])

            # Vectorize (fire-and-forget)
            try:
                symptom_data = {
                    "recorded_at": recorded_at,
                    "notes": data.notes,
                    "symptoms": [
                        {
                            "symptom_name": item.symptom_name,
                            "severity": item.severity,
                            "custom_label": item.custom_label,
                        }
                        for item in data.symptoms
                    ],
                }
                await self.checkin_vector_service.upsert_symptom_vector(
                    patient_id=patient_id,
                    symptom_entry_id=str(record.id),
                    symptom_data=symptom_data,
                    patient_age=0,
                    patient_gender="unknown",
                )
            except Exception as e:
                logger.error(f"Failed to vectorize symptoms for {patient_id}: {e}")

            return record

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database error",
                detail=str(e),
            )

    @with_postgres_session
    async def get_symptom_history(
        self,
        patient_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 20,
        offset: int = 0,
        *,
        postgres_session: AsyncSession,
    ) -> Tuple[List[SymptomEntry], int]:
        try:
            query = (
                select(SymptomEntry)
                .options(selectinload(SymptomEntry.items))
                .where(SymptomEntry.patient_id == patient_id)
            )
            count_query = select(func.count(SymptomEntry.id)).where(
                SymptomEntry.patient_id == patient_id
            )

            if start_date:
                query = query.where(SymptomEntry.recorded_at >= start_date)
                count_query = count_query.where(SymptomEntry.recorded_at >= start_date)
            if end_date:
                query = query.where(SymptomEntry.recorded_at <= end_date)
                count_query = count_query.where(SymptomEntry.recorded_at <= end_date)

            total = (await postgres_session.execute(count_query)).scalar() or 0

            query = query.order_by(SymptomEntry.recorded_at.desc()).limit(limit).offset(offset)
            result = await postgres_session.execute(query)
            return list(result.scalars().all()), total

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database error",
                detail=str(e),
            )

    @with_postgres_session
    async def get_symptom_trends(
        self,
        patient_id: str,
        period: str = "weekly",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        *,
        postgres_session: AsyncSession,
    ) -> Dict[str, Any]:
        try:
            if not start_date:
                start_date = date.today() - timedelta(days=90)
            if not end_date:
                end_date = date.today()

            trunc = "week" if period == "weekly" else "month"

            # Avg severity per period (join with items)
            stmt = (
                select(
                    func.date_trunc(trunc, SymptomEntry.recorded_at).label("period"),
                    func.avg(SymptomEntryItem.severity).label("avg_severity"),
                    func.count(func.distinct(SymptomEntry.id)).label("count"),
                )
                .join(SymptomEntryItem, SymptomEntryItem.symptom_entry_id == SymptomEntry.id)
                .where(
                    SymptomEntry.patient_id == patient_id,
                    cast(SymptomEntry.recorded_at, Date) >= start_date,
                    cast(SymptomEntry.recorded_at, Date) <= end_date,
                )
                .group_by("period")
                .order_by("period")
            )
            result = await postgres_session.execute(stmt)
            rows = result.all()

            # Top symptoms across entire date range
            top_stmt = (
                select(SymptomEntryItem.symptom_name, func.count().label("cnt"))
                .join(SymptomEntry, SymptomEntryItem.symptom_entry_id == SymptomEntry.id)
                .where(
                    SymptomEntry.patient_id == patient_id,
                    cast(SymptomEntry.recorded_at, Date) >= start_date,
                    cast(SymptomEntry.recorded_at, Date) <= end_date,
                )
                .group_by(SymptomEntryItem.symptom_name)
                .order_by(func.count().desc())
                .limit(5)
            )
            top_result = await postgres_session.execute(top_stmt)
            top_symptoms = [row[0] for row in top_result.all()]

            periods = [
                {
                    "label": row.period.strftime("%Y-%m-%d") if row.period else "",
                    "avg_severity": round(float(row.avg_severity), 1),
                    "count": row.count,
                    "top_symptoms": top_symptoms,
                }
                for row in rows
            ]

            current_streak, longest_streak = await self._compute_symptom_streaks(
                patient_id, postgres_session=postgres_session,
            )

            return {
                "periods": periods,
                "current_streak": current_streak,
                "longest_streak": longest_streak,
            }

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database error",
                detail=str(e),
            )

    async def _compute_symptom_streaks(
        self, patient_id: str, *, postgres_session: AsyncSession,
    ) -> Tuple[int, int]:
        result = await postgres_session.execute(
            select(cast(SymptomEntry.recorded_at, Date).label("day"))
            .where(SymptomEntry.patient_id == patient_id)
            .distinct()
            .order_by("day")
        )
        dates = sorted({row[0] for row in result.all()})
        if not dates:
            return 0, 0

        longest = 1
        current = 1
        for i in range(1, len(dates)):
            if (dates[i] - dates[i - 1]).days == 1:
                current += 1
                longest = max(longest, current)
            else:
                current = 1

        today = date.today()
        current_streak = 0
        for d in reversed(dates):
            expected = today - timedelta(days=current_streak)
            if d == expected:
                current_streak += 1
            else:
                break

        return current_streak, longest
