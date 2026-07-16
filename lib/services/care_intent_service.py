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
from sqlalchemy import delete as delete_stmt
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.dialects.postgresql import insert as pg_insert

from lib.ai_foundation.care_intents.contracts import DEFAULT_REVIEW_DAYS, StructuredCareIntent
from lib.core.postgres_store import PostgresStore
from lib.models.care_intent import CareIntent
from lib.models.care_intent_event import CareIntentEvent
from lib.utils.postgres_session_decorator import with_postgres_session

# 3+ consecutive misses = the provider should hear about it (escalation flag
# on the report-back; providers decide what to do, the system never does).
NEEDS_ATTENTION_CONSECUTIVE_MISSES = 3

logger = logging.getLogger(__name__)


class CareIntentService:
    def __init__(self, postgres_store: PostgresStore, provider_fcm=None):
        self.postgres_store = postgres_store
        self._provider_fcm = provider_fcm

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
        rows = list((await postgres_session.scalars(stmt)).all())
        if self._expire_stale(rows):
            await postgres_session.commit()
        if not include_inactive:
            rows = [r for r in rows if r.status == "active"]
        return rows

    @staticmethod
    def _expire_stale(rows: list[CareIntent]) -> bool:
        """Flip active intents past review_date to expired. Every read path
        runs this so no surface (patient, provider, AI) ever disagrees about
        whether an intent is live."""
        today = date.today()
        changed = False
        for r in rows:
            if r.status == "active" and r.review_date and r.review_date < today:
                r.status = "expired"
                changed = True
        return changed

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
        # Reactivating with a past review date would be lazily re-expired on
        # the very next AI read — resuming implies a fresh review window.
        if status == "active" and intent.review_date and intent.review_date < date.today():
            intent.review_date = date.today() + timedelta(days=DEFAULT_REVIEW_DAYS)
        await postgres_session.commit()
        await postgres_session.refresh(intent)
        return intent

    @with_postgres_session
    async def get_by_id(
        self,
        care_intent_id: UUID,
        *,
        author_id: UUID,
        postgres_session: AsyncSession,
    ) -> CareIntent | None:
        """Author-scoped fetch — a non-author gets None, never a peek at
        another provider's intent via its id."""
        return await postgres_session.scalar(
            select(CareIntent).where(
                and_(
                    CareIntent.care_intent_id == care_intent_id,
                    CareIntent.author_id == author_id,
                )
            )
        )

    @with_postgres_session
    async def update(
        self,
        care_intent_id: UUID,
        *,
        author_id: UUID,
        original_text: str,
        structured: StructuredCareIntent,
        postgres_session: AsyncSession,
    ) -> CareIntent | None:
        """Replace an intent's instruction (author-only). Adherence history
        stays attached — the behavior asked for evolved, it didn't restart."""
        intent = await postgres_session.scalar(
            select(CareIntent).where(
                and_(
                    CareIntent.care_intent_id == care_intent_id,
                    CareIntent.author_id == author_id,
                )
            )
        )
        if intent is None:
            return None
        intent.original_text = original_text
        intent.intent_type = structured.intent_type.value
        intent.domain = structured.domain.value
        intent.trigger_condition = structured.trigger_condition
        intent.cadence = structured.cadence.value
        intent.patient_summary = structured.patient_summary
        intent.success_criteria = structured.success_criteria
        intent.review_date = date.today() + timedelta(days=structured.review_days)
        # Editing revives an expired intent (fresh ask, fresh window) but must
        # not silently resume one the author deliberately paused.
        if intent.status == "expired":
            intent.status = "active"
        intent.escalated_at = None
        await postgres_session.commit()
        await postgres_session.refresh(intent)
        return intent

    @with_postgres_session
    async def delete(
        self,
        care_intent_id: UUID,
        *,
        author_id: UUID,
        postgres_session: AsyncSession,
    ) -> bool:
        """Hard delete (author-only), adherence events included — the FK has
        no cascade, so events go first."""
        intent = await postgres_session.scalar(
            select(CareIntent).where(
                and_(
                    CareIntent.care_intent_id == care_intent_id,
                    CareIntent.author_id == author_id,
                )
            )
        )
        if intent is None:
            return False
        await postgres_session.execute(
            delete_stmt(CareIntentEvent).where(
                CareIntentEvent.care_intent_id == care_intent_id
            )
        )
        await postgres_session.delete(intent)
        await postgres_session.commit()
        return True

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
        if self._expire_stale(rows):
            await postgres_session.commit()
        fresh = [r for r in rows if r.status == "active"]

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
                "created_at": str(r.created_at) if r.created_at else None,
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
        """Short per-intent recent-adherence phrase for LLM context, derived
        from the same stats the provider report uses — one implementation,
        one definition of "streak"."""
        summary = await self.adherence_summary(
            intent_ids, window_days=window_days, postgres_session=postgres_session,
        )
        hints: dict[UUID, str | None] = {}
        for intent_id in intent_ids:
            stats = summary.get(str(intent_id)) or {}
            if not stats.get("days_evaluated"):
                hints[intent_id] = None
                continue
            hint = f"followed {stats['days_followed']} of last {stats['days_evaluated']} evaluated days"
            if stats["consecutive_missed"] >= 2:
                hint += f"; missed the last {stats['consecutive_missed']}"
            if stats.get("barriers"):
                hint += f" (possible barrier: {stats['barriers'][0]})"
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
        """Upsert one day's verdicts — later scans of the same day overwrite.
        A verdict that puts an intent at the needs-attention threshold pings
        its author (once per miss-streak)."""
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

        missed_ids = [
            UUID(str(v["care_intent_id"])) for v in verdicts if v["status"] == "missed"
        ]
        if missed_ids:
            try:
                await self._escalate_if_needed(
                    missed_ids, patient_id, event_date, postgres_session=postgres_session,
                )
            except Exception:
                # Escalation is best-effort — never let a push failure poison
                # the recorded verdicts.
                logger.warning("Care-intent escalation failed", exc_info=True)

    async def _escalate_if_needed(
        self,
        missed_intent_ids: list[UUID],
        patient_id: str,
        event_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        """Ping the author when an intent CROSSES the consecutive-miss
        threshold. Exactly-at-threshold + escalated_at guard = one ping per
        miss-streak: day 4+ of the same streak stays quiet, a fresh streak
        after a followed day pings again."""
        summary = await self.adherence_summary(
            missed_intent_ids, postgres_session=postgres_session,
        )
        candidates = list((await postgres_session.scalars(
            select(CareIntent).where(CareIntent.care_intent_id.in_(missed_intent_ids))
        )).all())
        to_escalate: list[CareIntent] = []
        for intent in candidates:
            stats = summary.get(str(intent.care_intent_id)) or {}
            if stats.get("consecutive_missed") != NEEDS_ATTENTION_CONSECUTIVE_MISSES:
                continue
            # escalated_at is server-naive, event_date is the patient-local
            # judged day; safe because the morning scan always runs the
            # calendar day AFTER the day it judges, in every timezone.
            if intent.escalated_at and intent.escalated_at.date() >= event_date:
                continue
            to_escalate.append(intent)
        if not to_escalate:
            return

        # CLAIM before SEND: escalated_at is committed first so a concurrent
        # scan (or a send failure mid-loop) can never double-ping the author.
        # Worst case on send failure is one missed ping, never a duplicate.
        now = datetime.now().replace(tzinfo=None)
        for intent in to_escalate:
            intent.escalated_at = now
        await postgres_session.commit()

        from lib.models.patient import Patient

        patient = await postgres_session.scalar(
            select(Patient).where(Patient.patient_id == UUID(patient_id))
        )
        patient_name = (patient.first_name if patient else None) or "Your patient"

        fcm = self._get_provider_fcm()
        for intent in to_escalate:
            try:
                barriers = (summary.get(str(intent.care_intent_id)) or {}).get("barriers") or []
                barrier_line = f" Possible barrier: {barriers[0]}." if barriers else ""
                await fcm.send_fcm_notification_to_user_devices(
                    user_id=str(intent.author_id),
                    title=f"Adherence alert — {patient_name}",
                    body=(
                        f"{patient_name} has missed \"{intent.original_text}\" "
                        f"{NEEDS_ATTENTION_CONSECUTIVE_MISSES} days in a row.{barrier_line}"
                    ),
                    channel_key="alerts",
                    group_key="alert_group",
                    data={
                        "type": "care_intent_escalation",
                        "care_intent_id": str(intent.care_intent_id),
                        "patient_id": patient_id,
                    },
                )
                logger.info(
                    "care_intents.escalated | intent=%s author=%s patient=%s",
                    str(intent.care_intent_id)[:8], str(intent.author_id)[:8], patient_id[:8],
                )
            except Exception:
                logger.warning(
                    "Escalation push failed for intent %s (claimed — will not re-ping)",
                    str(intent.care_intent_id)[:8], exc_info=True,
                )

    def _get_provider_fcm(self):
        """Provider-app FCM client, built lazily (Firebase init needs prod
        credentials — tests and intent-free deployments never touch it)."""
        if self._provider_fcm is None:
            from lib.core.constants import FCMProjectEnum
            from lib.services.fcm_service import FCMService

            self._provider_fcm = FCMService(project=FCMProjectEnum.CARE_PROVIDER_APP)
        return self._provider_fcm

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
