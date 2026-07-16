"""Whole-person LLM analysis for the weightloss agent.

Turns holistic daily snapshots into three artifacts, all persisted in Mongo:

- ``DailyCoachAnalysis`` — one per patient per local day, generated after the
  day completes. Carries the ready-to-send morning message.
- ``EveningReview`` — light same-day check-in generated at the end-of-day
  checkpoint from partial data.
- ``WholePersonSummary`` — big-picture understanding, refreshed weekly or when
  a new InBody report lands.

There is deliberately no rule-based fallback: if the LLM call fails the
analysis stays ``failed_retrying`` and the caller retries later; no message is
delivered until an analysis exists.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from decouple import config
from loguru import logger
from motor.motor_asyncio import AsyncIOMotorCollection
from sqlalchemy import and_, select

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.core.postgres_store import PostgresStore
from lib.models.weight_loss_agent import WeightLossAgentEnrollment
from lib.schemas.weightloss_agent.holistic import (
    DailyCoachAnalysis,
    EveningReview,
    HolisticDailySnapshot,
    InbodyBaseline,
    PatientContext,
    WholePersonSummary,
)
from lib.services.weightloss_agent.holistic_data_service import (
    HolisticDataService,
)

SUMMARY_LOOKBACK_DAYS = 14
SUMMARY_STALE_AFTER_DAYS = 7

# Pinned model for all holistic analyses. An explicit model_id bypasses the
# gateway's task-based fallback chain — a failure halts and retries rather
# than degrading to another model, consistent with the no-fallback design.
HOLISTIC_MODEL_ID = config(
    "WEIGHTLOSS_HOLISTIC_MODEL_ID", default="gpt-5.6-terra"
)

COACH_SYSTEM_PROMPT = (
    "You are a supportive, precise weight-loss coach analysing one patient's "
    "real logged health data. Ground every statement in the numbers provided — "
    "never invent data. When a data block is missing, say it is not logged "
    "rather than guessing. Derive a personalised calorie target from the "
    "patient's basal metabolic rate and weight-loss goal when BMR is available "
    "(a moderate deficit, never below 1200 kcal). Never give medication dosing "
    "advice; at most note adherence and remind about prescribed schedules. "
    "Messages must be warm, specific, and reference actual numbers."
)


class HolisticSummaryService:
    def __init__(
        self,
        holistic_data_service: HolisticDataService,
        model_gateway: ModelGateway,
        daily_analyses_collection: AsyncIOMotorCollection,
        summaries_collection: AsyncIOMotorCollection,
        postgres_store: PostgresStore,
    ) -> None:
        self.holistic_data_service = holistic_data_service
        self.model_gateway = model_gateway
        self.daily_analyses_collection = daily_analyses_collection
        self.summaries_collection = summaries_collection
        self.postgres_store = postgres_store

    # ------------------------------------------------------------------
    # Enrollment helpers
    # ------------------------------------------------------------------

    async def _get_active_enrollment(
        self, patient_id: UUID
    ) -> Optional[WeightLossAgentEnrollment]:
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(WeightLossAgentEnrollment).where(
                    and_(
                        WeightLossAgentEnrollment.patient_id == patient_id,
                        WeightLossAgentEnrollment.is_active.is_(True),
                    )
                )
            )
            return result.scalars().first()

    async def _get_enrollment_by_id(
        self, enrollment_id: UUID
    ) -> Optional[WeightLossAgentEnrollment]:
        async with self.postgres_store.get_session() as session:
            return await session.get(WeightLossAgentEnrollment, enrollment_id)

    # ------------------------------------------------------------------
    # Daily coach analysis
    # ------------------------------------------------------------------

    async def get_daily_analysis(
        self, patient_id: UUID, target_date: date
    ) -> Optional[Dict[str, Any]]:
        doc = await self.daily_analyses_collection.find_one(
            {"patient_id": str(patient_id), "date": target_date.isoformat()}
        )
        if doc:
            doc.pop("_id", None)
        return doc

    async def generate_daily_coach_analysis(
        self,
        patient_id: UUID,
        target_date: date,
        *,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Generate (or return the existing) analysis for one completed day.

        Raises on LLM failure — the caller is responsible for scheduling a
        retry. The stored doc is left in ``failed_retrying`` so delivery
        stays blocked.
        """

        date_str = target_date.isoformat()
        existing = await self.get_daily_analysis(patient_id, target_date)
        if existing and existing.get("status") == "complete" and not force:
            logger.info(
                "holistic: daily analysis already complete patient={} date={}",
                patient_id,
                date_str,
            )
            return existing

        now = datetime.now(timezone.utc)
        attempts = (existing or {}).get("attempts", 0) + 1
        analysis_id = (existing or {}).get("analysis_id") or str(uuid4())

        enrollment = await self._get_active_enrollment(patient_id)
        enrollment_id = str(enrollment.enrollment_id) if enrollment else None

        await self.daily_analyses_collection.update_one(
            {"patient_id": str(patient_id), "date": date_str},
            {
                "$set": {
                    "analysis_id": analysis_id,
                    "enrollment_id": enrollment_id,
                    "status": "pending",
                    "attempts": attempts,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

        logger.info(
            "holistic: generating daily analysis patient={} date={} attempt={}",
            patient_id,
            date_str,
            attempts,
        )

        snapshot = await self.holistic_data_service.get_daily_snapshot(
            patient_id, target_date
        )
        context = await self.holistic_data_service.get_patient_context(patient_id)
        inbody = (
            await self.holistic_data_service.get_inbody_baseline(
                UUID(enrollment_id)
            )
            if enrollment_id
            else None
        )

        try:
            analysis, llm_meta = await self.model_gateway.extract(
                messages=self._daily_analysis_messages(context, inbody, snapshot),
                response_model=DailyCoachAnalysis,
                task=ModelTask.STRUCTURED_ANALYSIS,
                model_id=HOLISTIC_MODEL_ID,
            )
        except Exception as exc:
            logger.error(
                "holistic: LLM daily analysis FAILED patient={} date={} attempt={}: {}",
                patient_id,
                date_str,
                attempts,
                exc,
            )
            await self.daily_analyses_collection.update_one(
                {"patient_id": str(patient_id), "date": date_str},
                {
                    "$set": {
                        "status": "failed_retrying",
                        "error": str(exc),
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )
            raise

        doc_update = {
            "status": "complete",
            "error": None,
            "snapshot": snapshot.model_dump(),
            "analysis": analysis.model_dump(),
            "llm_model": getattr(llm_meta, "model_id", None),
            "updated_at": datetime.now(timezone.utc),
        }
        await self.daily_analyses_collection.update_one(
            {"patient_id": str(patient_id), "date": date_str},
            {"$set": doc_update},
        )

        logger.info(
            "holistic: daily analysis complete patient={} date={} "
            "diet={} activity={} glucose={} coverage={}",
            patient_id,
            date_str,
            analysis.diet.adherence,
            analysis.activity.adherence,
            analysis.glucose.control,
            snapshot.data_coverage,
        )

        result = await self.get_daily_analysis(patient_id, target_date)
        return result or doc_update

    # ------------------------------------------------------------------
    # Evening review (same-day, partial data)
    # ------------------------------------------------------------------

    async def generate_evening_review(
        self, patient_id: UUID, target_date: date
    ) -> EveningReview:
        """Same-day light review. Raises on LLM failure — caller skips the message."""

        snapshot = await self.holistic_data_service.get_daily_snapshot(
            patient_id, target_date
        )
        context = await self.holistic_data_service.get_patient_context(patient_id)

        review, _ = await self.model_gateway.extract(
            messages=[
                {"role": "system", "content": COACH_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "It is the end of the patient's day. Review today's "
                        "(possibly partial) data and produce the evening check-in.\n\n"
                        f"PATIENT:\n{self._dump(context)}\n\n"
                        f"TODAY ({snapshot.date}):\n{self._dump(snapshot)}"
                    ),
                },
            ],
            response_model=EveningReview,
            task=ModelTask.STRUCTURED_ANALYSIS,
            model_id=HOLISTIC_MODEL_ID,
        )

        now = datetime.now(timezone.utc)
        await self.daily_analyses_collection.update_one(
            {"patient_id": str(patient_id), "date": target_date.isoformat()},
            {
                "$set": {
                    "evening_review": review.model_dump(),
                    "evening_review_generated_at": now,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "analysis_id": str(uuid4()),
                    "status": "pending",
                    "attempts": 0,
                    "created_at": now,
                },
            },
            upsert=True,
        )

        logger.info(
            "holistic: evening review generated patient={} date={}",
            patient_id,
            target_date,
        )
        return review

    # ------------------------------------------------------------------
    # Whole-person summary
    # ------------------------------------------------------------------

    async def get_whole_person_summary(
        self, enrollment_id: UUID
    ) -> Optional[Dict[str, Any]]:
        doc = await self.summaries_collection.find_one(
            {"enrollment_id": str(enrollment_id)}, sort=[("generated_at", -1)]
        )
        if doc:
            doc.pop("_id", None)
        return doc

    async def refresh_summary_for_patient(
        self, patient_id: UUID, *, force: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Regenerate the summary for a patient's active enrollment, if any."""

        enrollment = await self._get_active_enrollment(patient_id)
        if not enrollment:
            logger.info(
                "holistic: no active enrollment for patient={} — skipping summary",
                patient_id,
            )
            return None
        return await self.generate_whole_person_summary(
            enrollment.enrollment_id, force=force
        )

    async def generate_whole_person_summary(
        self, enrollment_id: UUID, *, force: bool = False
    ) -> Dict[str, Any]:
        """Regenerate the big-picture summary unless a fresh one exists."""

        existing = await self.get_whole_person_summary(enrollment_id)
        if existing and not force:
            generated_at = existing.get("generated_at")
            if isinstance(generated_at, datetime):
                age = datetime.now(timezone.utc) - (
                    generated_at
                    if generated_at.tzinfo
                    else generated_at.replace(tzinfo=timezone.utc)
                )
                if age < timedelta(days=SUMMARY_STALE_AFTER_DAYS):
                    logger.info(
                        "holistic: whole-person summary still fresh enrollment={} "
                        "age_days={}",
                        enrollment_id,
                        age.days,
                    )
                    return existing

        enrollment = await self._get_enrollment_by_id(enrollment_id)
        if not enrollment:
            raise ValueError(f"Enrollment {enrollment_id} not found")

        patient_id = enrollment.patient_id
        timezone_name = await self.holistic_data_service.get_patient_timezone(
            patient_id
        )
        from zoneinfo import ZoneInfo

        today_local = datetime.now(ZoneInfo(timezone_name)).date()
        start = today_local - timedelta(days=SUMMARY_LOOKBACK_DAYS)
        end = today_local - timedelta(days=1)

        logger.info(
            "holistic: generating whole-person summary enrollment={} patient={} "
            "window={}..{}",
            enrollment_id,
            patient_id,
            start,
            end,
        )

        snapshots = await self.holistic_data_service.get_snapshot_range(
            patient_id, start, end
        )
        # Only ship days that actually carry data — keeps the prompt lean.
        informative = [s for s in snapshots if s.data_coverage]
        context = await self.holistic_data_service.get_patient_context(patient_id)
        inbody = await self.holistic_data_service.get_inbody_baseline(enrollment_id)

        days_json = "\n".join(self._dump(s) for s in informative) or "No daily data logged."

        summary, llm_meta = await self.model_gateway.extract(
            messages=[
                {"role": "system", "content": COACH_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Build a whole-person understanding of this patient from "
                        "their profile, latest InBody body-composition report and "
                        f"the last {SUMMARY_LOOKBACK_DAYS} days of logged data.\n\n"
                        f"PATIENT:\n{self._dump(context)}\n\n"
                        f"INBODY BASELINE:\n{self._dump(inbody) if inbody else 'No InBody report available.'}\n\n"
                        f"DAILY DATA ({len(informative)} days with data):\n{days_json}"
                    ),
                },
            ],
            response_model=WholePersonSummary,
            task=ModelTask.STRUCTURED_ANALYSIS,
            model_id=HOLISTIC_MODEL_ID,
        )

        doc = {
            "summary_id": str(uuid4()),
            "enrollment_id": str(enrollment_id),
            "patient_id": str(patient_id),
            "generated_at": datetime.now(timezone.utc),
            "days_analyzed": len(informative),
            "inbody_report_id": inbody.report_id if inbody else None,
            "summary": summary.model_dump(),
            "llm_model": getattr(llm_meta, "model_id", None),
            "context": {
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "target_weight_kg": enrollment.target_weight_kg,
                "target_bmi": enrollment.target_bmi,
            },
        }
        await self.summaries_collection.insert_one(doc)
        doc.pop("_id", None)

        logger.info(
            "holistic: whole-person summary stored enrollment={} summary_id={} "
            "days_analyzed={}",
            enrollment_id,
            doc["summary_id"],
            len(informative),
        )
        return doc

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dump(model: Any) -> str:
        return json.dumps(model.model_dump(exclude_none=True), default=str)

    def _daily_analysis_messages(
        self,
        context: PatientContext,
        inbody: Optional[InbodyBaseline],
        snapshot: HolisticDailySnapshot,
    ) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": COACH_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Analyse this patient's completed day and produce the "
                    "structured verdicts plus the next-morning coach message. "
                    "The morning message must state what happened, whether it "
                    "supports their weight-loss progress, and what to focus on "
                    "today.\n\n"
                    f"PATIENT:\n{self._dump(context)}\n\n"
                    f"INBODY BASELINE:\n{self._dump(inbody) if inbody else 'No InBody report available.'}\n\n"
                    f"DAY UNDER REVIEW ({snapshot.date}):\n{self._dump(snapshot)}"
                ),
            },
        ]
