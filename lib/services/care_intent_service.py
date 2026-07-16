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

from lib.ai_foundation.care_intents.contracts import StructuredCareIntent
from lib.core.postgres_store import PostgresStore
from lib.models.care_intent import CareIntent
from lib.utils.postgres_session_decorator import with_postgres_session

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

        return [
            {
                "author_name": r.author_name,
                "author_role": r.author_role,
                "original_text": r.original_text,
                "intent_type": r.intent_type,
                "domain": r.domain,
                "trigger_condition": r.trigger_condition,
                "cadence": r.cadence,
            }
            for r in fresh
        ]
