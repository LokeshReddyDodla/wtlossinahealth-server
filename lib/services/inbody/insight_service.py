"""Contextual InBody insights — "since your last scan".

On successful extraction, compare the new scan against the previous one and
interpret the changes through the behaviour window in between (meals,
protein, steps, workouts, sleep, glucose — via the Patient Data Hub). One
structured LLM call produces the typed insight; it is stored once per report
in Mongo and read everywhere (patient app, care-provider view, notification).

No fallback text by design: if the LLM call fails, the insight document stays
``failed_retrying`` and the ARQ task retries with backoff; nothing canned is
ever delivered.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from decouple import config
from loguru import logger
from motor.motor_asyncio import AsyncIOMotorCollection
from sqlalchemy import select

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.core.postgres_store import PostgresStore
from lib.models.patient_inbody_report import PatientInbodyReport
from lib.schemas.inbody import (
    InbodyContextualInsight,
    MetricDelta,
)
from lib.schemas.patient_data_hub import WindowAggregates
from lib.services.patient_data_hub_service import PatientDataHubService

INBODY_INSIGHT_MODEL_ID = config(
    "INBODY_INSIGHT_MODEL_ID", default="gpt-5.6-terra"
)

# Metrics compared scan-to-scan, with the direction that counts as improvement
# while losing weight ("down" = lower is better).
DELTA_METRICS: Dict[str, str] = {
    "weight": "down",
    "skeletal_muscle_mass": "up",
    "body_fat_mass": "down",
    "percent_body_fat": "down",
    "visceral_fat_level": "down",
    "basal_metabolic_rate": "up",
    "ecw_ratio": "down",
}

INSIGHT_SYSTEM_PROMPT = (
    "You are a body-composition coach interpreting a patient's new InBody "
    "scan against their previous scan and what they actually did in between. "
    "Ground every statement in the numbers provided — never invent data. When "
    "a domain has no data in the window, name it in data_gaps and do not "
    "speculate about it. Connect composition changes to behaviour honestly "
    "(e.g. muscle loss + low protein + no strength training). Never give "
    "medication dosing advice. The patient-facing story must be warm and "
    "specific; the care-provider summary clinical and terse."
)


def _measurement_map(analysis: Dict[str, Any]) -> Dict[str, float]:
    result: Dict[str, float] = {}
    for measurement in analysis.get("measurements") or []:
        name = measurement.get("name")
        value = measurement.get("value")
        if name and value is not None:
            try:
                result[name] = float(value)
            except (TypeError, ValueError):
                continue
    return result


def compute_deltas(
    previous: Dict[str, Any], current: Dict[str, Any]
) -> List[MetricDelta]:
    prev_map = _measurement_map(previous)
    curr_map = _measurement_map(current)
    deltas: List[MetricDelta] = []
    for metric, better in DELTA_METRICS.items():
        prev_value = prev_map.get(metric)
        curr_value = curr_map.get(metric)
        if prev_value is None or curr_value is None:
            deltas.append(MetricDelta(metric=metric, previous=prev_value,
                                      current=curr_value))
            continue
        change = round(curr_value - prev_value, 2)
        if change == 0:
            direction = "unchanged"
        elif (change < 0) == (better == "down"):
            direction = "improved"
        else:
            direction = "worsened"
        deltas.append(
            MetricDelta(
                metric=metric,
                previous=prev_value,
                current=curr_value,
                change=change,
                direction=direction,
            )
        )
    return deltas


class InbodyInsightService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        analyses_collection: AsyncIOMotorCollection,
        insights_collection: AsyncIOMotorCollection,
        data_hub: PatientDataHubService,
        model_gateway: ModelGateway,
    ) -> None:
        self.postgres_store = postgres_store
        self.analyses_collection = analyses_collection
        self.insights_collection = insights_collection
        self.data_hub = data_hub
        self.model_gateway = model_gateway

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get_insight(self, report_id: UUID) -> Optional[Dict[str, Any]]:
        doc = await self.insights_collection.find_one(
            {"report_id": str(report_id)}
        )
        if doc:
            doc.pop("_id", None)
        return doc

    async def get_latest_insight(
        self, patient_id: UUID
    ) -> Optional[Dict[str, Any]]:
        doc = await self.insights_collection.find_one(
            {"patient_id": str(patient_id), "status": "complete"},
            sort=[("created_at", -1)],
        )
        if doc:
            doc.pop("_id", None)
        return doc

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    async def generate_insight(
        self, report_id: UUID, *, force: bool = False
    ) -> Dict[str, Any]:
        """Generate (or return) the contextual insight for one report.

        Raises on LLM failure — the caller (ARQ task) owns retries; the
        stored doc is left ``failed_retrying`` so nothing is delivered
        until a real insight exists.
        """

        existing = await self.get_insight(report_id)
        if existing and existing.get("status") == "complete" and not force:
            return existing

        report, previous = await self._report_pair(report_id)
        patient_id = report.patient_id

        current_doc = await self.analyses_collection.find_one(
            {"report_id": str(report_id)}
        )
        if not current_doc or not current_doc.get("analysis"):
            raise ValueError(
                f"Report {report_id} has no extracted analysis to interpret"
            )
        current_analysis = current_doc["analysis"]

        now = datetime.now(timezone.utc)
        attempts = (existing or {}).get("attempts", 0) + 1
        insight_id = (existing or {}).get("insight_id") or str(uuid4())

        is_baseline = previous is None
        window_start: Optional[date] = None
        window_end: date = report.report_date
        previous_analysis: Optional[Dict[str, Any]] = None
        deltas: List[MetricDelta] = []

        if previous is not None:
            previous_doc = await self.analyses_collection.find_one(
                {"report_id": str(previous.report_id)}
            )
            previous_analysis = (previous_doc or {}).get("analysis")
            if previous_analysis:
                deltas = compute_deltas(previous_analysis, current_analysis)
                window_start = previous.report_date
            else:
                is_baseline = True

        if window_start is None:
            # Baseline: interpret the scan against the last 30 days of habits.
            window_start = window_end - timedelta(days=30)

        await self.insights_collection.update_one(
            {"report_id": str(report_id)},
            {
                "$set": {
                    "insight_id": insight_id,
                    "patient_id": str(patient_id),
                    "previous_report_id": (
                        str(previous.report_id) if previous else None
                    ),
                    "is_baseline": is_baseline,
                    "status": "pending",
                    "attempts": attempts,
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

        logger.info(
            "inbody-insight: generating report={} patient={} baseline={} "
            "window={}..{} attempt={}",
            report_id,
            patient_id,
            is_baseline,
            window_start,
            window_end,
            attempts,
        )

        aggregates = await self.data_hub.get_window_aggregates(
            patient_id, window_start, window_end
        )

        try:
            insight, meta = await self.model_gateway.extract(
                messages=self._messages(
                    is_baseline=is_baseline,
                    current_analysis=current_analysis,
                    previous_analysis=previous_analysis,
                    deltas=deltas,
                    aggregates=aggregates,
                ),
                response_model=InbodyContextualInsight,
                task=ModelTask.STRUCTURED_ANALYSIS,
                model_id=INBODY_INSIGHT_MODEL_ID,
            )
        except Exception as exc:
            logger.error(
                "inbody-insight: LLM FAILED report={} attempt={}: {}",
                report_id,
                attempts,
                exc,
            )
            await self.insights_collection.update_one(
                {"report_id": str(report_id)},
                {
                    "$set": {
                        "status": "failed_retrying",
                        "error": str(exc),
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )
            raise

        await self.insights_collection.update_one(
            {"report_id": str(report_id)},
            {
                "$set": {
                    "status": "complete",
                    "error": None,
                    "deltas": [d.model_dump() for d in deltas],
                    "window_aggregates": aggregates.model_dump(),
                    "insight": insight.model_dump(),
                    "llm_model": meta.model_id,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        logger.info(
            "inbody-insight: complete report={} model={} gaps={}",
            report_id,
            meta.model_id,
            insight.data_gaps,
        )
        return (await self.get_insight(report_id)) or {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _report_pair(
        self, report_id: UUID
    ) -> Tuple[PatientInbodyReport, Optional[PatientInbodyReport]]:
        """The report plus the newest usable report dated before it."""
        async with self.postgres_store.get_session() as session:
            report = await session.get(PatientInbodyReport, report_id)
            if report is None:
                raise ValueError(f"InBody report {report_id} not found")
            result = await session.execute(
                select(PatientInbodyReport)
                .where(
                    PatientInbodyReport.patient_id == report.patient_id,
                    PatientInbodyReport.report_id != report.report_id,
                    PatientInbodyReport.status.in_(
                        ["extracted", "needs_review"]
                    ),
                    PatientInbodyReport.report_date <= report.report_date,
                )
                .order_by(PatientInbodyReport.report_date.desc())
                .limit(1)
            )
            previous = result.scalars().first()
        return report, previous

    @staticmethod
    def _dump(payload: Any) -> str:
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(exclude_none=True)
        return json.dumps(payload, default=str)

    def _messages(
        self,
        *,
        is_baseline: bool,
        current_analysis: Dict[str, Any],
        previous_analysis: Optional[Dict[str, Any]],
        deltas: List[MetricDelta],
        aggregates: WindowAggregates,
    ) -> List[Dict[str, str]]:
        if is_baseline:
            task_text = (
                "This is the patient's FIRST InBody scan on record — there is "
                "no previous scan to compare against. Interpret the scan "
                "itself plus their recent habits, framed as the baseline the "
                "next scan will be measured against."
            )
            comparison = "No previous scan."
        else:
            task_text = (
                "Interpret what changed since the previous scan and connect "
                "it to what the patient actually did in the window between "
                "the two scans."
            )
            comparison = (
                f"PREVIOUS SCAN ANALYSIS:\n{self._dump(previous_analysis)}\n\n"
                f"SCAN-TO-SCAN DELTAS:\n"
                f"{json.dumps([d.model_dump() for d in deltas])}"
            )
        return [
            {"role": "system", "content": INSIGHT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{task_text}\n\n"
                    f"CURRENT SCAN ANALYSIS:\n{self._dump(current_analysis)}\n\n"
                    f"{comparison}\n\n"
                    f"BEHAVIOUR WINDOW ({aggregates.start_date} → "
                    f"{aggregates.end_date}):\n{self._dump(aggregates)}"
                ),
            },
        ]
