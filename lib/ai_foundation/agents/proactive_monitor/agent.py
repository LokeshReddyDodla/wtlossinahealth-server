"""
Proactive Monitor Agent — background health monitoring with direct data fetch.

Fetches patient data directly from Qdrant (deterministic, no LLM tool-calling),
then uses a single LLM call to analyze the data and produce structured insights.

Pipeline:
    1. Fetch data directly from Qdrant (glucose, meals, activity)
    2. Format into readable text
    3. Single LLM call → structured ScanInsights
    4. Dedup + escalation via InsightTracker
    5. Publish insights to EventBus
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from lib.ai_foundation.agents.base import BaseAgent
from lib.ai_foundation.agents.state import AgentInput, AgentOutput
from lib.ai_foundation.events.schemas import HealthEvent, HealthEventType
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.retrieval.base import RetrievalRequest

from .contracts import (
    BatchScanResult,
    HealthInsight,
    InsightCategory,
    InsightSeverity,
    ScanInsights,
    ScanResult,
)

logger = logging.getLogger(__name__)

# Data types to check in each scan
_SCAN_DATA_TYPES = [
    "cgm_summary_stats",    # daily glucose overview (TIR, avg, variability)
    "cgm_range_stats",      # time in range breakdown
    "hyper_event",          # specific glucose spike events
    "hypo_event",           # specific hypo events (safety critical)
    "meal",                 # meals logged
    "smbg",                 # finger-prick readings
    "fitness_overview",     # steps, active minutes
    "sleep",                # sleep duration/quality
    "vital",                # weight, BP, heart rate
]

# Keys to strip from payloads before sending to LLM (noise reduction)
_STRIP_KEYS = frozenset({
    "data_type", "source", "patient_id", "embedding", "text_repr",
    "patient_age", "patient_gender", "vector_updated_at",
    "start_time", "end_time", "day_of_week", "is_weekend",
    "week_number", "month", "time_of_day_bucket", "report_id",
})


class ProactiveMonitorAgent(BaseAgent):
    """Background health monitor that fetches data and classifies insights.

    Unlike the HealthQueryAgent which uses the ReasoningEngine for interactive
    queries, this agent fetches data directly from Qdrant (deterministic) and
    uses a single LLM call to produce structured insights. This is faster,
    cheaper, and more reliable for background monitoring.

    Example::

        monitor = ProactiveMonitorAgent(
            gateway=gateway,
            qdrant=qdrant_retriever,
            event_bus=event_bus,
        )

        # Scan a single patient
        result = await monitor.scan_patient("patient_123", "Sarah")
        for insight in result.insights:
            print(f"[{insight.severity}] {insight.title}: {insight.body}")

        # Scan a batch (for cron jobs)
        results = await monitor.scan_batch(["p1", "p2", "p3"])
    """

    agent_id = "proactive_monitor_v2"

    def __init__(
        self,
        *,
        gateway: Any,
        qdrant: Any,
        event_bus: Any | None = None,
        prompts: Any | None = None,
        memory: Any | None = None,
        insight_tracker: Any | None = None,
    ) -> None:
        super().__init__(gateway=gateway, prompts=prompts, event_bus=event_bus, memory=memory)
        self._qdrant = qdrant
        self._insight_tracker = insight_tracker

    # -- Public API ---------------------------------------------------------

    async def scan_patient(
        self,
        patient_id: str,
        patient_name: str | None = None,
        tz_name: str | None = None,
    ) -> ScanResult:
        """Scan a single patient's recent data and generate insights."""
        from zoneinfo import ZoneInfo
        from .scheduling import DEFAULT_TIMEZONE

        start = time.perf_counter()

        try:
            # 1. Determine scan window in patient's local timezone
            tz = ZoneInfo(tz_name or DEFAULT_TIMEZONE)
            now = datetime.now(tz)
            hour = now.hour
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            today = now.strftime("%Y-%m-%d")

            if hour < 12:
                scan_date = yesterday
                scan_label = "yesterday"
                scan_period = "morning"
            elif hour < 17:
                scan_date = today
                scan_label = "today so far"
                scan_period = "afternoon"
            else:
                scan_date = today
                scan_label = "today"
                scan_period = "evening"

            # 2. Fetch data directly from Qdrant — deterministic, no LLM
            data_text, domain_counts = await self._fetch_patient_data(
                patient_id, patient_name, scan_date,
            )

            logger.info(
                "Scan %s: %s — %s",
                patient_id, scan_label,
                ", ".join(f"{k}={v}" for k, v in domain_counts.items()) or "no data",
            )

            # 3. Load patient facts for context
            facts_text = await self._load_facts(patient_id)

            # 4. Single LLM call → structured ScanInsights
            display_name = patient_name or "this patient"
            insights = await self._analyze_data(
                data_text=data_text,
                patient_id=patient_id,
                patient_name=display_name,
                scan_label=scan_label,
                scan_period=scan_period,
                facts_text=facts_text,
                has_data=bool(data_text),
            )

            # 5. Dedup + escalation via InsightTracker
            insights = await self._filter_insights(patient_id, insights)

            # 6. Publish insights via EventBus
            for insight in insights:
                await self._publish_insight(insight)

            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ScanResult(
                patient_id=patient_id,
                scan_date=scan_date,
                insights=insights,
                scan_duration_ms=elapsed_ms,
                data_available=bool(data_text),
            )

        except Exception as exc:
            logger.error("Scan failed for patient %s: %s", patient_id, exc, exc_info=True)
            return ScanResult(
                patient_id=patient_id,
                error=str(exc),
                scan_duration_ms=int((time.perf_counter() - start) * 1000),
                data_available=False,
            )

    async def scan_batch(
        self,
        patient_ids: list[str],
        patient_names: dict[str, str] | None = None,
        patient_timezones: dict[str, str] | None = None,
    ) -> BatchScanResult:
        """Scan multiple patients. Runs sequentially to avoid overwhelming the LLM."""
        start = time.perf_counter()
        names = patient_names or {}
        tzs = patient_timezones or {}
        batch = BatchScanResult(total_patients=len(patient_ids))

        for pid in patient_ids:
            try:
                result = await self.scan_patient(pid, names.get(pid), tz_name=tzs.get(pid))
                batch.results.append(result)
                batch.scanned += 1
                if result.error:
                    batch.errors += 1
                if result.has_insights:
                    batch.with_insights += 1
                    batch.total_insights += len(result.insights)
                    batch.total_alerts += result.alert_count
            except Exception as exc:
                logger.warning("Scan failed for %s: %s", pid, exc)
                batch.scanned += 1
                batch.errors += 1

        batch.duration_ms = int((time.perf_counter() - start) * 1000)

        logger.info(
            "Proactive scan: %d/%d patients, %d insights (%d alerts), %dms",
            batch.scanned, batch.total_patients,
            batch.total_insights, batch.total_alerts,
            batch.duration_ms,
        )
        return batch

    # -- BaseAgent interface (not typically used for this agent) -------------

    async def run(self, input: AgentInput) -> AgentOutput:
        """Run scan for the patient in context. Satisfies BaseAgent interface."""
        patient_id = input.context.patient_id
        if not patient_id:
            return AgentOutput(message="No patient ID provided for scan.", is_ready=False)

        result = await self.scan_patient(patient_id)
        if not result.insights:
            return AgentOutput(message="No noteworthy patterns detected.", is_ready=True)

        messages = [f"[{i.severity.value}] {i.title}: {i.body}" for i in result.insights]
        return AgentOutput(
            message="\n".join(messages),
            is_ready=True,
            data={
                "insights": [i.model_dump(mode="json") for i in result.insights],
                "scan_duration_ms": result.scan_duration_ms,
            },
        )

    # -- Pipeline steps (private) -------------------------------------------

    async def _fetch_patient_data(
        self,
        patient_id: str,
        patient_name: str | None,
        scan_date: str,
    ) -> tuple[str, dict[str, int]]:
        """Fetch health data directly from Qdrant for the scan date.

        Returns (formatted_text, domain_counts) where domain_counts
        maps data_type → number of records found.
        """
        results = await self._qdrant.retrieve_filtered(RetrievalRequest(
            query="",
            patient_ids=[patient_id],
            data_types=_SCAN_DATA_TYPES,
            date_start=scan_date,
            date_end=scan_date,
            limit=50,
        ))

        # Filter out profile records (Qdrant always includes them)
        results = [r for r in results if r.data_type != "profile"]

        if not results:
            return "", {}

        # Group by data type and format
        domain_counts: dict[str, int] = {}
        by_type: dict[str, list[dict]] = {}
        for r in results:
            dt = r.data_type or r.payload.get("data_type", "unknown")
            domain_counts[dt] = domain_counts.get(dt, 0) + 1
            by_type.setdefault(dt, []).append(r.payload)

        sections: list[str] = []
        name = patient_name or "Patient"

        for dt, items in by_type.items():
            label = dt.replace("_", " ").upper()
            lines: list[str] = [f"## {label} ({len(items)} records)"]
            for item in items:
                clean = {
                    k: v for k, v in item.items()
                    if k not in _STRIP_KEYS and v is not None
                }
                parts: list[str] = []
                for k, v in clean.items():
                    if isinstance(v, dict):
                        inner = ", ".join(
                            f"{ik}: {iv}" for ik, iv in v.items() if iv is not None
                        )
                        if inner:
                            parts.append(f"{k}: ({inner})")
                    elif isinstance(v, list) and v and isinstance(v[0], dict):
                        parts.append(f"{k}: {len(v)} items")
                    else:
                        parts.append(f"{k}: {v}")
                lines.append("- " + ", ".join(parts))

            sections.append("\n".join(lines))

        header = f"# Health Data for {name} on {scan_date}\n"
        return header + "\n\n".join(sections), domain_counts

    async def _load_facts(self, patient_id: str) -> str:
        """Load patient facts from memory for context."""
        if not self.memory:
            return ""
        try:
            raw_facts = await self.memory.get_patient_facts(patient_id)
            if not raw_facts:
                return ""
            lines = []
            for f in raw_facts[:6]:
                lines.append(f"- {f.fact_type}: {f.value}")
            return "Patient facts:\n" + "\n".join(lines)
        except Exception:
            return ""

    async def _analyze_data(
        self,
        data_text: str,
        patient_id: str,
        patient_name: str,
        scan_label: str,
        scan_period: str,
        facts_text: str,
        has_data: bool,
    ) -> list[HealthInsight]:
        """Single LLM call: data → structured ScanInsights."""
        greetings = {
            "morning": "Good morning",
            "afternoon": "Hi",
            "evening": "Here's your day wrap-up",
        }
        greeting = greetings.get(scan_period, "Hi")

        if not has_data:
            # No data at all — produce an engagement insight without LLM
            return [HealthInsight(
                category=InsightCategory.ENGAGEMENT_DROP,
                severity=InsightSeverity.ATTENTION,
                title="No health data recorded",
                body=f"{greeting} {patient_name}! No data was logged {scan_label}. Keep logging to help us track your health!",
                patient_id=patient_id,
                suggested_query="Why is it important to log my health data regularly?",
            )]

        context_parts = [data_text]
        if facts_text:
            context_parts.append(facts_text)

        system_prompt = (
            "You are a friendly health assistant writing push notifications for a patient. "
            "Produce 1-3 structured health insights from the data provided.\n\n"
            f"Time of day: {scan_period}. Data is from {scan_label}.\n\n"
            "RULES:\n"
            "1. EVERY insight must reference specific data from the records below.\n"
            "2. Include BOTH concerns AND positives. If glucose is in range, that's worth noting. "
            "If meals were logged consistently, acknowledge it.\n"
            "3. If a domain has no records, you may note the absence (e.g. no activity logged).\n"
            "4. Address the patient DIRECTLY using 'you/your' — like a friendly coach. "
            "Use their first name naturally (e.g. 'Asish, you had...' not 'Dr Asish Satapathy had...').\n"
            f"5. Start the body with an appropriate greeting ('{greeting}' for {scan_period}). "
            "Keep it natural, not forced.\n"
            f"6. Refer to the time as '{scan_label}' — don't include full dates like 2026-03-26.\n"
            "7. Title must be under 45 characters. Body must be under 180 characters.\n"
            "8. ALWAYS include a suggested_query — a follow-up question the patient could ask.\n\n"
            "CATEGORIES — pick the one that fits best:\n"
            "Concerns: glucose_spike, glucose_hypo, glucose_worsening, meal_missed, "
            "meal_high_carb, meal_low_protein, fitness_inactive, sleep_poor, engagement_drop\n"
            "Positives: glucose_improving, fitness_streak, sleep_improving, goal_progress\n"
            "Neutral: general\n\n"
            "Severity levels: info (positive/FYI), attention (worth noting), "
            "warning (needs attention), alert (urgent)"
        )

        try:
            scan_insights, _ = await self.gateway.extract(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n\n".join(context_parts)},
                ],
                response_model=ScanInsights,
                task=ModelTask.CLASSIFICATION,
            )
            for insight in scan_insights.insights:
                insight.patient_id = patient_id
            return scan_insights.insights
        except Exception as exc:
            logger.warning("Insight analysis failed: %s", exc, exc_info=True)
            return []

    async def _filter_insights(
        self,
        patient_id: str,
        insights: list[HealthInsight],
    ) -> list[HealthInsight]:
        """Filter insights through dedup + escalation via InsightTracker.

        Only checks dedup — does NOT record. The caller must call
        record_insight() for the insight it actually sends as a notification.
        """
        if not self._insight_tracker:
            return insights

        filtered: list[HealthInsight] = []
        for insight in insights:
            try:
                should_send, escalated_severity = await self._insight_tracker.should_send(
                    patient_id, insight.category.value,
                )
                if should_send:
                    if escalated_severity != "info":
                        insight.severity = InsightSeverity(escalated_severity)
                    filtered.append(insight)
                else:
                    logger.debug(
                        "Dedup: skipping %s for patient %s (sent recently)",
                        insight.category.value, patient_id,
                    )
            except Exception as exc:
                logger.warning("InsightTracker error for %s: %s", patient_id, exc)
                filtered.append(insight)

        return filtered

    async def record_insight(self, patient_id: str, insight: HealthInsight) -> None:
        """Record that an insight was actually sent as a notification."""
        if not self._insight_tracker:
            return
        await self._insight_tracker.record(
            patient_id,
            insight.category.value,
            insight.severity.value,
            insight.body,
        )

    async def _publish_insight(self, insight: HealthInsight) -> None:
        """Publish an insight to the EventBus for notification delivery."""
        if not self.event_bus:
            return

        await self.event_bus.publish(HealthEvent(
            event_type=HealthEventType.PROACTIVE_INSIGHT,
            patient_id=insight.patient_id,
            data={
                "insight_id": insight.insight_id,
                "category": insight.category.value,
                "severity": insight.severity.value,
                "title": insight.title,
                "body": insight.body,
                "actionable": insight.actionable,
                "suggested_query": insight.suggested_query,
            },
            source_agent=self.agent_id,
        ))
