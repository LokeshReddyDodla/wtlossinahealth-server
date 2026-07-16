"""Care Intent service — CRUD + read shapes for provider-authored guidance.

The AI reads intents through ``get_active_context`` (dict rows, no ORM
objects) — that's the duck-typed dependency injected into ai_foundation's
monitor and context loader, keeping ai_foundation free of service imports.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.dialects.postgresql import insert as pg_insert

from lib.ai_foundation.care_intents.contracts import StructuredCareIntent
from lib.core.postgres_store import PostgresStore
from lib.models.care_intent import CareIntent
from lib.models.care_intent_event import CareIntentEvent
from lib.utils.postgres_session_decorator import with_postgres_session

# 3+ consecutive misses = the provider should hear about it (escalation flag
# on the report-back; providers decide what to do, the system never does).
NEEDS_ATTENTION_CONSECUTIVE_MISSES = 3

logger = logging.getLogger(__name__)


class CareIntentService:
    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store

    @with_postgres_session
    async def create(
        self,
        *,
        patient_id: UUID,
        author_id: UUID,
        author_role: str,
        author_name: str,
        original_text: str,
        structured: StructuredCareIntent,
        postgres_session: AsyncSession,
    ) -> CareIntent:
        intent = CareIntent(
            patient_id=patient_id,
            author_id=author_id,
            author_role=author_role,
            author_name=author_name,
            original_text=original_text,
            intent_type=structured.intent_type.value,
            domain=structured.domain.value,
            trigger_condition=structured.trigger_condition,
            cadence=structured.cadence.value,
            patient_summary=structured.patient_summary,
            success_criteria=structured.success_criteria,
            review_date=date.today() + timedelta(days=structured.review_days),
            status="active",
        )
        postgres_session.add(intent)
        await postgres_session.commit()
        await postgres_session.refresh(intent)
        return intent

    @with_postgres_session
    async def list_for_patient(
        self,
        patient_id: UUID,
        *,
        include_inactive: bool = False,
        postgres_session: AsyncSession,
    ) -> list[CareIntent]:
        stmt = select(CareIntent).where(CareIntent.patient_id == patient_id)
        if not include_inactive:
            stmt = stmt.where(CareIntent.status == "active")
        stmt = stmt.order_by(CareIntent.created_at.desc())
        return list((await postgres_session.scalars(stmt)).all())

    @with_postgres_session
    async def update_status(
        self,
        care_intent_id: UUID,
        status: str,
        *,
        author_id: UUID | None = None,
        postgres_session: AsyncSession,
    ) -> CareIntent | None:
        """Set status. When ``author_id`` is given, only the author may change
        their own intent — other providers pause via their own judgment call
        with the author, not silently."""
        conditions = [CareIntent.care_intent_id == care_intent_id]
        if author_id is not None:
            conditions.append(CareIntent.author_id == author_id)
        intent = await postgres_session.scalar(select(CareIntent).where(and_(*conditions)))
        if intent is None:
            return None
        intent.status = status
        await postgres_session.commit()
        await postgres_session.refresh(intent)
        return intent

    # -- AI-facing read (duck-typed dependency for ai_foundation) -----------

    @with_postgres_session
    async def get_active_context(
        self,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> list[dict]:
        """Active, unexpired intents as plain dicts for LLM context assembly.

        Intents past review_date are lazily expired here — the read path is
        the only place that must never serve a stale instruction, so the
        transition happens where it matters instead of via a sweeper job.
        """
        stmt = (
            select(CareIntent)
            .where(
                and_(
                    CareIntent.patient_id == UUID(patient_id),
                    CareIntent.status == "active",
                )
            )
            .order_by(CareIntent.created_at.desc())
        )
        rows = list((await postgres_session.scalars(stmt)).all())

        today = datetime.now().date()
        fresh: list[CareIntent] = []
        expired_any = False
        for r in rows:
            if r.review_date and r.review_date < today:
                r.status = "expired"
                expired_any = True
            else:
                fresh.append(r)
        if expired_any:
            await postgres_session.commit()

        hints = await self._adherence_hints(
            [r.care_intent_id for r in fresh], postgres_session=postgres_session,
        )
        return [
            {
                "care_intent_id": str(r.care_intent_id),
                "author_name": r.author_name,
                "author_role": r.author_role,
                "original_text": r.original_text,
                "intent_type": r.intent_type,
                "domain": r.domain,
                "trigger_condition": r.trigger_condition,
                "cadence": r.cadence,
                "adherence_hint": hints.get(r.care_intent_id),
            }
            for r in fresh
        ]

    async def _adherence_hints(
        self,
        intent_ids: list[UUID],
        *,
        postgres_session: AsyncSession,
        window_days: int = 7,
    ) -> dict[UUID, str | None]:
        """Short per-intent recent-adherence phrase for LLM context, e.g.
        "followed 4 of last 6 evaluated days; missed the last 2"."""
        if not intent_ids:
            return {}
        since = date.today() - timedelta(days=window_days)
        stmt = (
            select(CareIntentEvent)
            .where(
                and_(
                    CareIntentEvent.care_intent_id.in_(intent_ids),
                    CareIntentEvent.event_date >= since,
                )
            )
            .order_by(CareIntentEvent.event_date.desc())
        )
        rows = list((await postgres_session.scalars(stmt)).all())
        by_intent: dict[UUID, list[CareIntentEvent]] = {}
        for r in rows:
            by_intent.setdefault(r.care_intent_id, []).append(r)

        hints: dict[UUID, str | None] = {i: None for i in intent_ids}
        for intent_id, events in by_intent.items():
            judged = [e for e in events if e.status in ("followed", "missed")]
            if not judged:
                continue
            followed = sum(1 for e in judged if e.status == "followed")
            hint = f"followed {followed} of last {len(judged)} evaluated days"
            streak = 0
            for e in judged:  # newest first
                if e.status == "missed":
                    streak += 1
                else:
                    break
            if streak >= 2:
                hint += f"; missed the last {streak}"
            barrier = next((e.note for e in events if e.note), None)
            if barrier:
                hint += f" (possible barrier: {barrier})"
            hints[intent_id] = hint
        return hints

    @with_postgres_session
    async def record_adherence(
        self,
        verdicts: list[dict],
        *,
        patient_id: str,
        event_date: date,
        postgres_session: AsyncSession,
    ) -> None:
        """Upsert one day's verdicts — later scans of the same day overwrite."""
        if not verdicts:
            return
        for v in verdicts:
            stmt = pg_insert(CareIntentEvent).values(
                care_intent_id=UUID(str(v["care_intent_id"])),
                patient_id=UUID(patient_id),
                event_date=event_date,
                status=v["status"],
                note=v.get("note"),
            ).on_conflict_do_update(
                constraint="uq_care_intent_event_day",
                set_={"status": v["status"], "note": v.get("note")},
            )
            await postgres_session.execute(stmt)
        await postgres_session.commit()

    @with_postgres_session
    async def adherence_summary(
        self,
        intent_ids: list[UUID],
        *,
        window_days: int = 14,
        postgres_session: AsyncSession,
    ) -> dict[str, dict]:
        """Provider report-back per intent: daily events + rate + attention flag."""
        if not intent_ids:
            return {}
        since = date.today() - timedelta(days=window_days)
        stmt = (
            select(CareIntentEvent)
            .where(
                and_(
                    CareIntentEvent.care_intent_id.in_(intent_ids),
                    CareIntentEvent.event_date >= since,
                )
            )
            .order_by(CareIntentEvent.event_date.desc())
        )
        rows = list((await postgres_session.scalars(stmt)).all())
        by_intent: dict[UUID, list[CareIntentEvent]] = {}
        for r in rows:
            by_intent.setdefault(r.care_intent_id, []).append(r)

        out: dict[str, dict] = {}
        for intent_id in intent_ids:
            events = by_intent.get(intent_id, [])
            judged = [e for e in events if e.status in ("followed", "missed")]
            followed = sum(1 for e in judged if e.status == "followed")
            streak = 0
            for e in judged:  # newest first
                if e.status == "missed":
                    streak += 1
                else:
                    break
            out[str(intent_id)] = {
                "days_evaluated": len(judged),
                "days_followed": followed,
                "consecutive_missed": streak,
                "needs_attention": streak >= NEEDS_ATTENTION_CONSECUTIVE_MISSES,
                "barriers": [e.note for e in events if e.note][:3],
                "daily": [
                    {"date": str(e.event_date), "status": e.status, "note": e.note}
                    for e in events
                ],
            }
        return out
