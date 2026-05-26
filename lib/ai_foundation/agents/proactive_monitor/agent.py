"""
Proactive Monitor Agent — background health monitoring with direct data fetch.

Fetches patient data directly from Qdrant (deterministic, no LLM tool-calling),
then uses a single LLM call to analyze the data and produce structured insights.

Pipeline:
    1. Fetch data directly from Qdrant (glucose, meals, activity)
    2. Format into readable text
    3. Single LLM call → structured ScanInsights (with static fallback)
    4. Dedup + escalation via InsightTracker
    5. Publish insights to EventBus
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from string import Template
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from lib.ai_foundation.agents.base import BaseAgent
from lib.ai_foundation.agents.health_query.contracts import HealthDataType
from lib.ai_foundation.agents.state import AgentInput, AgentOutput
from lib.ai_foundation.events.schemas import HealthEvent, HealthEventType
from lib.ai_foundation.models.gateway import LLMResponse
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.retrieval.base import RetrievalRequest

from .scheduling import DEFAULT_TIMEZONE
from .contracts import (
    BatchScanResult,
    DailyBrief,
    EventTrigger,
    HealthInsight,
    InsightCategory,
    InsightSeverity,
    LLM_INSIGHT_CATEGORIES_PROMPT,
    ScanInsights,
    ScanResult,
    SEVERITY_RANK,
    TRIGGER_DATA_TYPES,
    TRIGGER_LABELS,
    TriggerAnchor,
)

logger = logging.getLogger(__name__)


async def _maybe_await(result: Any) -> None:
    """Await values only when a dependency returns an awaitable."""
    if inspect.isawaitable(result):
        await result

# Data types fetched during a cron sweep (broad view of the patient's day).
# Sourced from HealthDataType so any rename in the data layer is caught at
# import time, not as a silent miss when Qdrant returns nothing.
_SCAN_DATA_TYPES: list[HealthDataType] = [
    HealthDataType.CGM_SUMMARY,
    HealthDataType.CGM_RANGE,
    HealthDataType.HYPER_EVENT,
    HealthDataType.HYPO_EVENT,
    HealthDataType.RAPID_SPIKE_EVENT,
    HealthDataType.RAPID_DROP_EVENT,
    HealthDataType.MEAL,
    HealthDataType.SMBG,
    HealthDataType.FITNESS_OVERVIEW,
    HealthDataType.SLEEP,
    HealthDataType.SLEEP_CHECKIN,
    HealthDataType.MOOD_ENTRY,
    HealthDataType.SYMPTOM_ENTRY,
    HealthDataType.VITAL,
    HealthDataType.DIET_PLAN,
    HealthDataType.FITNESS_PLAN,
    HealthDataType.PATIENT_WORKOUT,
]

# Keys to strip from payloads before sending to LLM (noise reduction)
_STRIP_KEYS = frozenset({
    "data_type", "source", "patient_id", "embedding", "text_repr",
    "patient_age", "patient_gender", "vector_updated_at",
    "start_time", "end_time", "day_of_week", "is_weekend",
    "week_number", "month", "time_of_day_bucket", "report_id",
})

# Max concurrent patient scans in a batch
_SCAN_CONCURRENCY = 5


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
    _SCAN_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_scan.md"
    _BRIEF_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_scan_brief.md"
    _EVENT_SCAN_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_event_scan.md"
    _scan_prompt_template: str | None = None
    _brief_prompt_template: str | None = None
    _event_scan_prompt_template: str | None = None

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

    @classmethod
    def _get_scan_prompt_template(cls) -> str:
        """Load and cache the system scan prompt template."""
        if cls._scan_prompt_template is None:
            cls._scan_prompt_template = cls._SCAN_PROMPT_PATH.read_text()
        return cls._scan_prompt_template

    @classmethod
    def _get_brief_prompt_template(cls) -> str:
        """Load and cache the morning brief prompt template."""
        if cls._brief_prompt_template is None:
            cls._brief_prompt_template = cls._BRIEF_PROMPT_PATH.read_text()
        return cls._brief_prompt_template

    @classmethod
    def _get_event_scan_prompt_template(cls) -> str:
        """Load and cache the event-driven scan prompt template."""
        if cls._event_scan_prompt_template is None:
            cls._event_scan_prompt_template = cls._EVENT_SCAN_PROMPT_PATH.read_text()
        return cls._event_scan_prompt_template

    # -- Public API ---------------------------------------------------------

    async def scan_patient(
        self,
        patient_id: str,
        patient_name: str | None = None,
        tz_name: str | None = None,
        *,
        trigger: EventTrigger | None = None,
        anchor: TriggerAnchor | None = None,
    ) -> ScanResult:
        """Scan a patient and produce structured health insights.

        Two modes share this entry point so the harness (fetch → LLM →
        dedup → publish) is implemented once:

        * **Cron sweep** (``trigger=None``) — fetches the full data-type
          set, produces 1-3 insights (morning runs collapse them into a
          single daily brief).
        * **Event-driven** (``trigger`` set) — narrow fetch via
          ``TRIGGER_DATA_TYPES``, single focused insight built around the
          ``anchor`` payload. The LLM is always the brain — no static
          templating for any trigger.
        """
        start = time.perf_counter()
        is_event = trigger is not None
        trace_id = f"pm_evt_{uuid4().hex[:14]}" if is_event else f"pm_{uuid4().hex[:16]}"

        try:
            # 1. Window + greeting in patient-local time
            tz = ZoneInfo(tz_name or DEFAULT_TIMEZONE)
            now = datetime.now(tz)
            scan_date, scan_label, scan_period = self._scan_window(now)
            greeting = self._greeting_for(scan_period)
            display_name = patient_name or "this patient"

            # 2. Narrow vs full fetch
            data_types = (
                TRIGGER_DATA_TYPES[trigger] if is_event else _SCAN_DATA_TYPES
            )
            data_text, domain_counts = await self._fetch_patient_data(
                patient_id=patient_id,
                patient_name=display_name,
                scan_date=scan_date,
                data_types=data_types,
                trigger=trigger,
            )

            logger.info(
                "Scan %s (%s): %s — %s",
                patient_id,
                trigger.value if is_event else "cron",
                scan_label,
                ", ".join(f"{k}={v}" for k, v in domain_counts.items()) or "no data",
            )

            # 3. Facts + medications
            facts_text = await self._load_facts(patient_id)
            med_text = await self._load_medications(patient_id)
            if med_text:
                facts_text = (
                    f"{facts_text}\n\nPatient Medications:\n{med_text}"
                    if facts_text
                    else f"Patient Medications:\n{med_text}"
                )

            # 4. Langfuse input trace
            session_id = (
                f"proactive_event_{trigger.value}_{scan_date}"
                if is_event
                else f"proactive_scan_{scan_date}"
            )
            await _maybe_await(self.gateway.set_langfuse_context(
                session_id=session_id,
                user_id=patient_id,
            ))
            await _maybe_await(self.gateway.langfuse_trace_input(
                trace_id=trace_id,
                name="proactive_monitor_event" if is_event else "proactive_monitor",
                input_text=data_text[:500] if data_text else "(no data)",
                metadata={
                    "agent": self.agent_id,
                    "scan_date": scan_date,
                    "scan_period": scan_period,
                    "domain_counts": domain_counts,
                    "patient_name": patient_name,
                    "trigger": trigger.value if is_event else None,
                    "anchor": anchor.model_dump() if anchor else None,
                },
            ))

            # 5. Single LLM call (or static engagement-drop for empty cron data)
            insights, llm_meta = await self._analyze(
                data_text=data_text,
                patient_id=patient_id,
                patient_name=display_name,
                scan_label=scan_label,
                scan_period=scan_period,
                greeting=greeting,
                facts_text=facts_text,
                has_data=bool(data_text),
                domain_counts=domain_counts,
                trigger=trigger,
                anchor=anchor,
            )

            # 6. Dedup + escalation
            insights = await self._filter_insights(patient_id, insights)
            for insight in insights:
                insight.data.setdefault("trace_id", trace_id)
                if is_event:
                    insight.data.setdefault("trigger", trigger.value)

            # Observability: log every insight about to ship.
            for ins in insights:
                logger.info(
                    "proactive_monitor.published_insight | patient=%s mode=%s cat=%s severity=%s title=%r body=%r data_len=%d facts_len=%d counts=%s",
                    patient_id[:8],
                    trigger.value if is_event else "cron",
                    ins.category.value,
                    ins.severity.value,
                    ins.title,
                    ins.body,
                    len(data_text or ""),
                    len(facts_text or ""),
                    domain_counts or {},
                )

            # 7. Publish
            publish_results = await asyncio.gather(
                *[self._publish_insight(insight) for insight in insights],
                return_exceptions=True,
            )
            for insight, pub_result in zip(insights, publish_results):
                if isinstance(pub_result, Exception):
                    logger.warning(
                        "Failed to publish insight %s for patient %s: %s",
                        insight.insight_id, patient_id, pub_result,
                    )

            elapsed_ms = int((time.perf_counter() - start) * 1000)

            # 8. Langfuse output trace
            trace_meta: dict[str, Any] = {
                "latency_ms": elapsed_ms,
                "insights_count": len(insights),
            }
            if is_event:
                trace_meta["trigger"] = trigger.value
            if llm_meta is not None:
                trace_meta["model_id"] = llm_meta.model_id
                trace_meta["cost_usd"] = llm_meta.usage.cost.total_cost
                trace_meta["input_tokens"] = llm_meta.usage.input_tokens
                trace_meta["output_tokens"] = llm_meta.usage.output_tokens
            await _maybe_await(self.gateway.langfuse_trace_output(
                trace_id=trace_id,
                output_text="; ".join(f"[{i.severity.value}] {i.title}" for i in insights) or "(no insights)",
                metadata=trace_meta,
            ))

            return ScanResult(
                patient_id=patient_id,
                scan_date=scan_date,
                insights=insights,
                scan_duration_ms=elapsed_ms,
                data_available=bool(data_text),
            )

        except Exception as exc:
            logger.error(
                "Scan failed for patient %s (%s): %s",
                patient_id, trigger.value if is_event else "cron", exc, exc_info=True,
            )
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
        """Scan multiple patients with controlled concurrency."""
        start = time.perf_counter()
        names = patient_names or {}
        tzs = patient_timezones or {}
        batch = BatchScanResult(total_patients=len(patient_ids))
        semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)

        async def _scan_one(pid: str) -> ScanResult | None:
            async with semaphore:
                try:
                    return await self.scan_patient(pid, names.get(pid), tz_name=tzs.get(pid))
                except Exception as exc:
                    logger.warning("Scan failed for %s: %s", pid, exc)
                    return None

        results = await asyncio.gather(*[_scan_one(pid) for pid in patient_ids])

        for result in results:
            batch.scanned += 1
            if result is None:
                batch.errors += 1
                continue
            batch.results.append(result)
            if result.error:
                batch.errors += 1
            if result.has_insights:
                batch.with_insights += 1
                batch.total_insights += len(result.insights)
                batch.total_alerts += result.alert_count

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

    @staticmethod
    def _scan_window(now: datetime) -> tuple[str, str, str]:
        """Return (scan_date, scan_label, scan_period) for patient-local ``now``."""
        if now.hour < 12:
            return (now - timedelta(days=1)).strftime("%Y-%m-%d"), "yesterday", "morning"
        if now.hour < 17:
            return now.strftime("%Y-%m-%d"), "today so far", "afternoon"
        return now.strftime("%Y-%m-%d"), "today", "evening"

    _GREETINGS: dict[str, str] = {
        "morning": "Good morning",
        "afternoon": "Hi",
        "evening": "Here's your day wrap-up",
    }

    @classmethod
    def _greeting_for(cls, scan_period: str) -> str:
        """Single source for patient-facing greetings, keyed by scan period."""
        return cls._GREETINGS.get(scan_period, "Hi")

    async def _fetch_patient_data(
        self,
        patient_id: str,
        patient_name: str,
        scan_date: str,
        data_types: list[HealthDataType],
        trigger: EventTrigger | None = None,
    ) -> tuple[str, dict[str, int]]:
        """Fetch health data from Qdrant for the scan date.

        Returns (formatted_text, domain_counts) where domain_counts
        maps data_type → number of records found.
        """
        results = await self._qdrant.retrieve_filtered(RetrievalRequest(
            query="",
            patient_ids=[patient_id],
            data_types=[dt.value for dt in data_types],
            date_start=scan_date,
            date_end=scan_date,
            limit=50 if trigger is None else 30,
        ))

        # Filter out profile records (Qdrant always includes them)
        results = [r for r in results if r.data_type != HealthDataType.PROFILE.value]

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

        if trigger is not None:
            header = f"# Health Data for {patient_name} on {scan_date} (trigger: {trigger.value})\n"
        else:
            header = f"# Health Data for {patient_name} on {scan_date}\n"
        return header + "\n\n".join(sections), domain_counts

    _GOAL_KEYS = frozenset({
        "health_goal", "weight_goal", "glucose_target_tir",
        "weight_target", "steps_target", "sleep_target", "calorie_target",
    })

    async def _load_facts(self, patient_id: str) -> str:
        """Load patient facts from memory, with goals in a dedicated section."""
        if not self.memory:
            return ""
        try:
            raw_facts = await self.memory.get_patient_facts(patient_id)
            if not raw_facts:
                return ""

            goals = [f for f in raw_facts if f.key in self._GOAL_KEYS]
            other = [f for f in raw_facts if f.key not in self._GOAL_KEYS][:6]

            parts: list[str] = []
            if goals:
                lines = [f"- {f.key}: {f.value}" for f in goals]
                parts.append("Patient GOALS (track progress against these):\n" + "\n".join(lines))
            if other:
                lines = [f"- {f.key}: {f.value}" for f in other]
                parts.append("Patient facts:\n" + "\n".join(lines))
            return "\n\n".join(parts)
        except Exception:
            return ""

    async def _load_medications(self, patient_id: str) -> str:
        """Load all medications from Qdrant (no date filter — persistent context)."""
        try:
            results = await self._qdrant.retrieve_filtered(
                RetrievalRequest(
                    patient_ids=[patient_id],
                    data_types=[HealthDataType.MEDICATION.value],
                    limit=5,
                )
            )
            for r in results:
                dt = r.data_type or r.payload.get("data_type")
                if dt == HealthDataType.MEDICATION.value:
                    text = r.payload.get("text_repr", "")
                    if text:
                        return text
        except Exception:
            pass
        return ""

    async def _analyze(
        self,
        *,
        data_text: str,
        patient_id: str,
        patient_name: str,
        scan_label: str,
        scan_period: str,
        greeting: str,
        facts_text: str,
        has_data: bool,
        domain_counts: dict[str, int] | None = None,
        trigger: EventTrigger | None = None,
        anchor: TriggerAnchor | None = None,
    ) -> tuple[list[HealthInsight], LLMResponse | None]:
        """Single entry-point analyzer. Routes to the correct prompt and
        response_model based on whether this is an event scan, a morning
        brief, or a regular afternoon/evening cron sweep.

        Falls back to a static engagement-drop insight only when the cron
        sweep has zero data — that's not bypassing the LLM for response
        wording, it's recognising there is nothing to send to the LLM.
        """
        if trigger is None and not has_data:
            return [HealthInsight(
                category=InsightCategory.ENGAGEMENT_DROP,
                severity=InsightSeverity.ATTENTION,
                title="📋 No health data recorded",
                body=f"{greeting} {patient_name}! No data was logged {scan_label}. Keep logging to help us track your health!",
                patient_id=patient_id,
                suggested_query="Why is it important to log my health data regularly?",
            )], None

        context_parts: list[str] = []
        if trigger is not None:
            anchor_text = (
                "\n".join(f"- {k}: {v}" for k, v in anchor.model_dump().items())
                if anchor is not None
                else "(none)"
            )
            context_parts.append(f"TRIGGER ANCHOR:\n{anchor_text}")
        if data_text:
            context_parts.append(data_text)
        if facts_text:
            context_parts.append(facts_text)

        # Morning cron → daily brief; event or other cron → ScanInsights.
        if trigger is None and scan_period == "morning":
            return await self._llm_daily_brief(
                context_parts=context_parts,
                greeting=greeting,
                scan_label=scan_label,
                scan_period=scan_period,
                patient_id=patient_id,
                patient_name=patient_name,
                domain_counts=domain_counts,
            )

        return await self._llm_scan_insights(
            context_parts=context_parts,
            greeting=greeting,
            scan_label=scan_label,
            scan_period=scan_period,
            patient_id=patient_id,
            patient_name=patient_name,
            domain_counts=domain_counts,
            trigger=trigger,
        )

    async def _llm_scan_insights(
        self,
        *,
        context_parts: list[str],
        greeting: str,
        scan_label: str,
        scan_period: str,
        patient_id: str,
        patient_name: str,
        domain_counts: dict[str, int] | None,
        trigger: EventTrigger | None,
    ) -> tuple[list[HealthInsight], LLMResponse | None]:
        """LLM call producing structured ScanInsights.

        Cron mode (trigger=None) → 1-3 insights via system_scan.md.
        Event mode (trigger set) → at most 1 insight via system_event_scan.md.
        """
        if trigger is not None:
            template_str = self._get_event_scan_prompt_template()
            system_prompt = Template(template_str).safe_substitute(
                trigger_label=TRIGGER_LABELS[trigger],
                greeting=greeting,
                patient_name=patient_name,
                categories=LLM_INSIGHT_CATEGORIES_PROMPT,
            )
        else:
            template_str = self._get_scan_prompt_template()
            system_prompt = Template(template_str).safe_substitute(
                greeting=greeting,
                scan_label=scan_label,
                scan_period=scan_period,
                categories=LLM_INSIGHT_CATEGORIES_PROMPT,
                patient_name=patient_name,
            )

        try:
            scan_insights, llm_meta = await self.gateway.extract(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n\n".join(context_parts)},
                ],
                response_model=ScanInsights,
                task=ModelTask.CLASSIFICATION,
            )
            insights = (
                scan_insights.insights[:1] if trigger is not None else scan_insights.insights
            )
            for insight in insights:
                insight.patient_id = patient_id
            return insights, llm_meta
        except Exception as exc:
            mode = trigger.value if trigger is not None else "cron"
            logger.warning("Insight analysis failed (%s): %s", mode, exc, exc_info=True)
            if trigger is not None:
                # Event mode: stay silent rather than ship a templated message.
                return [], None
            counts = domain_counts or {}
            summary = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in counts.items())
            return [HealthInsight(
                category=InsightCategory.GENERAL,
                severity=InsightSeverity.INFO,
                title="📊 Your daily health check",
                body=f"{greeting} {patient_name}! We found {summary} {scan_label}. Open the app for details.",
                patient_id=patient_id,
                suggested_query=f"How was my health {scan_label}?",
            )], None

    async def _llm_daily_brief(
        self,
        *,
        context_parts: list[str],
        greeting: str,
        scan_label: str,
        scan_period: str,
        patient_id: str,
        patient_name: str,
        domain_counts: dict[str, int] | None,
    ) -> tuple[list[HealthInsight], LLMResponse | None]:
        """Morning cron: produce a single DailyBrief via system_scan_brief.md."""
        system_prompt = Template(self._get_brief_prompt_template()).safe_substitute(
            greeting=greeting,
            scan_label=scan_label,
            scan_period=scan_period,
            categories=LLM_INSIGHT_CATEGORIES_PROMPT,
            patient_name=patient_name,
        )

        try:
            brief, llm_meta = await self.gateway.extract(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n\n".join(context_parts)},
                ],
                response_model=DailyBrief,
                task=ModelTask.CLASSIFICATION,
            )
            return [HealthInsight(
                category=InsightCategory.DAILY_BRIEF,
                severity=brief.top_severity,
                title=brief.title,
                body=brief.body,
                patient_id=patient_id,
                suggested_query=brief.suggested_query,
                data={"categories_covered": [c.value for c in brief.categories_covered]},
            )], llm_meta
        except Exception as exc:
            logger.warning("Daily brief analysis failed: %s", exc, exc_info=True)
            counts = domain_counts or {}
            summary = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in counts.items())
            return [HealthInsight(
                category=InsightCategory.GENERAL,
                severity=InsightSeverity.INFO,
                title="📋 Your morning brief",
                body=f"{greeting} {patient_name}! We found {summary} {scan_label}. Open the app for details.",
                patient_id=patient_id,
                suggested_query=f"How was my health {scan_label}?",
            )], None

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
        dedup_cache: dict[str, tuple[bool, str, int]] = {}

        for insight in insights:
            # Daily brief: check covered categories, send if ANY are fresh
            if insight.category == InsightCategory.DAILY_BRIEF:
                covered = insight.data.get("categories_covered", [])
                any_fresh = False
                for cat in covered:
                    try:
                        check = dedup_cache.get(cat)
                        if check is None:
                            check = await self._insight_tracker.should_send(patient_id, cat)
                            dedup_cache[cat] = check
                        if check[0]:
                            any_fresh = True
                    except Exception as exc:
                        logger.warning("InsightTracker error for %s/%s: %s", patient_id, cat, exc)
                        any_fresh = True
                if any_fresh or not covered:
                    filtered.append(insight)
                else:
                    logger.debug("Dedup: skipping daily_brief for patient %s (all categories sent recently)", patient_id)
                continue

            category = insight.category.value
            try:
                check = dedup_cache.get(category)
                if check is None:
                    check = await self._insight_tracker.should_send(patient_id, category)
                    dedup_cache[category] = check

                should_send, escalated_severity, _consecutive_days = check
                if should_send:
                    escalated = InsightSeverity(escalated_severity)
                    if SEVERITY_RANK[escalated.value] > SEVERITY_RANK[insight.severity.value]:
                        insight.severity = escalated
                    filtered.append(insight)
                else:
                    logger.debug(
                        "Dedup: skipping %s for patient %s (sent recently)",
                        category,
                        patient_id,
                    )
            except Exception as exc:
                logger.warning("InsightTracker error for %s: %s", patient_id, exc)
                filtered.append(insight)

        return filtered

    async def record_insight(
        self,
        patient_id: str,
        insight: HealthInsight,
        *,
        trigger: str | None = None,
    ) -> None:
        """Record that an insight was actually sent as a notification.

        For daily briefs, records each covered category so afternoon/evening
        scans correctly dedup against content already mentioned in the brief.
        """
        if not self._insight_tracker:
            return

        trigger_val = trigger or "cron"

        if insight.category == InsightCategory.DAILY_BRIEF:
            # Record the brief itself (with insight_id) for history/feedback
            await self._insight_tracker.record(
                patient_id,
                insight.category.value,
                insight.severity.value,
                insight.body,
                insight_id=insight.insight_id,
                title=insight.title,
                suggested_query=insight.suggested_query,
                trace_id=insight.data.get("trace_id"),
                trigger=trigger_val,
            )
            # Record dedup-only entries for each covered category (no insight_id)
            # so afternoon/evening scans correctly skip already-mentioned topics
            covered = insight.data.get("categories_covered", [])
            for cat in covered:
                await self._insight_tracker.record(
                    patient_id,
                    cat,
                    insight.severity.value,
                    insight.body,
                )
            return

        await self._insight_tracker.record(
            patient_id,
            insight.category.value,
            insight.severity.value,
            insight.body,
            insight_id=insight.insight_id,
            title=insight.title,
            suggested_query=insight.suggested_query,
            trace_id=insight.data.get("trace_id"),
            trigger=trigger_val,
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
                "trace_id": insight.data.get("trace_id"),
            },
            source_agent=self.agent_id,
        ))
