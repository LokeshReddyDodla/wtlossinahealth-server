"""GLP-1 weekly symptom logger with escalation detection."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorCollection

from lib.schemas.weightloss_agent.symptoms import (
    WeeklySymptomsCreate,
    WeeklySymptomsRecord,
)
from lib.services.weightloss_agent.analytics_service import AnalyticsService


class Glp1SymptomsService:
    def __init__(
        self,
        weekly_symptoms_collection: AsyncIOMotorCollection,
        analytics_service: AnalyticsService,
    ) -> None:
        self.weekly_symptoms_collection = weekly_symptoms_collection
        self.analytics_service = analytics_service

    async def log_weekly_symptoms(
        self, payload: WeeklySymptomsCreate
    ) -> WeeklySymptomsRecord:
        record_id = uuid4()
        captured_at = datetime.now(timezone.utc)
        severity = self._compute_overall_severity(payload)

        escalation_reason = None
        escalation_triggered = False
        if severity >= 2:
            escalation_triggered = await self._has_persistent_moderate_plus(
                payload.user_id, payload.week_end
            )
            if escalation_triggered:
                escalation_reason = "grade_2_persistent_14d"
        if (
            payload.hypoglycemia_events > 0
            and payload.insulin_or_sulfonylurea
        ):
            escalation_triggered = True
            escalation_reason = "recurrent_hypoglycemia"

        doc = {
            "record_id": str(record_id),
            "user_id": str(payload.user_id),
            "payload": self._serialize_payload(payload),
            "week_start": self._to_datetime(payload.week_start),
            "week_end": self._to_datetime(payload.week_end),
            "captured_at": captured_at,
            "severity_grade_overall": severity,
            "escalation_triggered": escalation_triggered,
            "escalation_reason": escalation_reason,
            "provenance": {"component": "glp1_symptoms"},
        }
        await self.weekly_symptoms_collection.insert_one(doc)

        await self.analytics_service.emit_event(
            event_type="symptoms_logged",
            user_id=str(payload.user_id),
            payload={
                "severity_grade_overall": severity,
                "escalation_triggered": escalation_triggered,
            },
        )

        if escalation_triggered:
            await self.analytics_service.emit_event(
                event_type="escalation_triggered",
                user_id=str(payload.user_id),
                payload={"reason": escalation_reason},
                severity="critical",
            )
            await self.analytics_service.record_audit_trace(
                {
                    "change_reason": escalation_reason,
                    "evidence_refs": [
                        {"type": "symptom_record", "record_id": str(record_id)}
                    ],
                }
            )

        return WeeklySymptomsRecord(
            record_id=record_id,
            user_id=payload.user_id,
            medication_name=payload.medication_name,
            medication_dose_mg=payload.medication_dose_mg,
            week_start=payload.week_start,
            week_end=payload.week_end,
            symptoms=payload.symptoms,
            fasting_bg_events=payload.fasting_bg_events,
            hypoglycemia_events=payload.hypoglycemia_events,
            insulin_or_sulfonylurea=payload.insulin_or_sulfonylurea,
            notes=payload.notes,
            captured_at=captured_at,
            severity_grade_overall=severity,
            escalation_triggered=escalation_triggered,
            escalation_reason=escalation_reason,
            provenance=doc["provenance"],
        )

    async def _has_persistent_moderate_plus(
        self, user_id: UUID, week_end: date
    ) -> bool:
        lookback_start = self._to_datetime(week_end - timedelta(days=14))
        cursor = self.weekly_symptoms_collection.find(
            {
                "user_id": str(user_id),
                "week_end": {"$gte": lookback_start},
                "severity_grade_overall": {"$gte": 2},
            }
        )
        count = 0
        async for _ in cursor:
            count += 1
            if count >= 1:
                return True
        return False

    def _compute_overall_severity(
        self, payload: WeeklySymptomsCreate
    ) -> int:
        if not payload.symptoms:
            return 0
        return max(symptom.severity_grade for symptom in payload.symptoms)

    def _to_datetime(self, value: date) -> datetime:
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)

    def _serialize_payload(self, payload_model: WeeklySymptomsCreate) -> dict:
        return json.loads(
            json.dumps(payload_model.model_dump(), default=str)
        )
