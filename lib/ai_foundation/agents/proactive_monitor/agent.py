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
import hashlib
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
from lib.core.qdrant_store import QDRANT_COLLECTION, QdrantStore

from .scheduling import DEFAULT_TIMEZONE
from .contracts import (
    BatchScanResult,
    DailyBrief,
    EventTrigger,
    HealthInsight,
    InsightCategory,
    InsightSeverity,
    LLM_INSIGHT_CATEGORIES_PROMPT,
    MealLoggedAnchor,
    SMBGLoggedAnchor,
    ScanInsights,
    ScanResult,
    SEVERITY_RANK,
    SymptomLoggedAnchor,
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
        metabolic_service: Any | None = None,
        care_intents: Any | None = None,
    ) -> None:
        super().__init__(gateway=gateway, prompts=prompts, event_bus=event_bus, memory=memory)
        self._qdrant = qdrant
        self._insight_tracker = insight_tracker
        self._metabolic = metabolic_service
        # Duck-typed reader with get_active_context(patient_id) -> list[dict]
        # (CareIntentService in production) — ai_foundation stays import-free
        # of the service layer.
        self._care_intents = care_intents

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

    # -- Trigger record fetch ------------------------------------------------

    _TRIGGER_RECORD_KEYS: dict[type, tuple[str, str]] = {
        MealLoggedAnchor: ("meal_id", "meal"),
        SMBGLoggedAnchor: ("reading_id", "smbg"),
        SymptomLoggedAnchor: ("symptom_entry_id", "symptom_entry"),
    }

    async def _fetch_trigger_record(
        self,
        patient_id: str,
        anchor: TriggerAnchor,
    ) -> dict[str, Any] | None:
        """Fetch the specific Qdrant record that fired this event.

        Uses O(1) point-ID lookup (MD5 of entity ID) — same pattern as
        refs.py._retrieve_simple. Returns the payload dict or None.
        """
        anchor_type = type(anchor)
        mapping = self._TRIGGER_RECORD_KEYS.get(anchor_type)
        if mapping is None:
            return None

        id_field, expected_data_type = mapping
        entity_id = getattr(anchor, id_field)
        point_id = hashlib.md5(entity_id.encode()).hexdigest()

        try:
            store = QdrantStore()  # process-wide singleton — cheap to "construct"
            async with store.get_client() as client:
                points = await client.retrieve(
                    collection_name=QDRANT_COLLECTION,
                    ids=[point_id],
                    with_payload=True,
                )
        except Exception as exc:
            logger.debug("Trigger record fetch failed for %s: %s", entity_id, exc)
            return None

        if not points:
            return None
        payload = points[0].payload or {}
        if payload.get("patient_id") != patient_id:
            return None
        if payload.get("data_type") != expected_data_type:
            return None
        return dict(payload)

    def _format_record(self, payload: dict[str, Any]) -> str:
        """Format a single Qdrant payload into a readable text block."""
        clean = {
            k: v for k, v in payload.items()
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
        return ", ".join(parts)

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

            # 2. Fetch trigger record (O(1) by ID) + context data
            trigger_record: dict[str, Any] | None = None
            if is_event and anchor is not None:
                trigger_record = await self._fetch_trigger_record(patient_id, anchor)

            data_types = (
                TRIGGER_DATA_TYPES[trigger] if is_event else _SCAN_DATA_TYPES
            )
            data_text, domain_counts = await self._fetch_patient_data(
                patient_id=patient_id,
                patient_name=display_name,
                scan_date=scan_date,
                data_types=data_types,
                trigger=trigger,
                exclude_record=trigger_record,
            )

            logger.info(
                "Scan %s (%s): %s — %s",
                patient_id,
                trigger.value if is_event else "cron",
                scan_label,
                ", ".join(f"{k}={v}" for k, v in domain_counts.items()) or "no data",
            )

            # 3. Facts + care-team intents + medications + metabolic profile
            facts_text = await self._load_facts(patient_id)
            care_intents = await self._get_care_intents(patient_id)
            care_text = self._format_care_intents_section(care_intents)
            if care_text:
                facts_text = f"{facts_text}\n\n{care_text}" if facts_text else care_text
            # Morning cron sees the completed previous day — the only window
            # where an adherence verdict isn't premature.
            if care_intents and not is_event and scan_period == "morning":
                await self._record_adherence(
                    patient_id, care_intents, data_text, scan_date, scan_label,
                )
            med_text = await self._load_medications(patient_id)
            if med_text:
                facts_text = (
                    f"{facts_text}\n\nPatient Medications:\n{med_text}"
                    if facts_text
                    else f"Patient Medications:\n{med_text}"
                )
            metabolic_text = await self._load_metabolic_profile(patient_id)
            if metabolic_text:
                facts_text = (
                    f"{facts_text}\n\n{metabolic_text}"
                    if facts_text
                    else metabolic_text
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
                input_text=(data_text[:500] if data_text
                            else (trigger_record.get("text_repr") or "(trigger record only)")[:500] if trigger_record
                            else "(no data)"),
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
                has_data=bool(data_text or trigger_record),
                domain_counts=domain_counts,
                trigger=trigger,
                anchor=anchor,
                trigger_record=trigger_record,
            )

            # 6. Dedup + escalation (skip for event-driven — each event is unique;
            #    notification_budget + arq job_id prevent spam).
            if not is_event:
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
                data_available=bool(data_text or trigger_record),
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
        exclude_record: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, int]]:
        """Fetch health data from Qdrant for the scan date.

        Returns (formatted_text, domain_counts) where domain_counts
        maps data_type → number of records found.

        When ``exclude_record`` is set, any payload whose ``meal_id`` or
        ``symptom_entry_id`` matches the excluded record is skipped — it
        will be presented separately as the trigger event.
        """
        if trigger is not None:
            prev_date = (
                datetime.strptime(scan_date, "%Y-%m-%d") - timedelta(days=1)
            ).strftime("%Y-%m-%d")
            fetch_start = prev_date
        else:
            fetch_start = scan_date

        results = await self._qdrant.retrieve_filtered(RetrievalRequest(
            query="",
            patient_ids=[patient_id],
            data_types=[dt.value for dt in data_types],
            date_start=fetch_start,
            date_end=scan_date,
            limit=50 if trigger is None else 30,
        ))

        # Filter out profile records (Qdrant always includes them)
        results = [r for r in results if r.data_type != HealthDataType.PROFILE.value]

        # Exclude the trigger record so it's not duplicated in context
        if exclude_record is not None:
            excl_meal = exclude_record.get("meal_id")
            excl_reading = exclude_record.get("reading_id")
            excl_symptom = exclude_record.get("symptom_entry_id")
            results = [
                r for r in results
                if not (
                    (excl_meal and r.payload.get("meal_id") == excl_meal)
                    or (excl_reading and r.payload.get("reading_id") == excl_reading)
                    or (excl_symptom and r.payload.get("symptom_entry_id") == excl_symptom)
                )
            ]

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
                lines.append("- " + self._format_record(item))

            sections.append("\n".join(lines))

        # Meal totals are computed in CODE, never by the LLM — small models
        # mis-add lists of numbers, and a wrong total in a notification is a
        # clinical-credibility bug (dietitian review 30/06).
        totals = self._meal_totals_section(
            by_type.get(HealthDataType.MEAL.value, []),
            trigger=trigger,
            trigger_record=exclude_record,
        )
        if totals:
            # First section, right under the trigger block — sitting totals are
            # the frame everything else must be read in.
            sections.insert(0, totals)

        if trigger is not None:
            header = f"# Supporting Context\n"
        else:
            header = f"# Health Data for {patient_name} on {scan_date}\n"
        return header + "\n\n".join(sections), domain_counts

    # Items logged within this window of the trigger meal are one sitting.
    _SITTING_WINDOW_MS = 90 * 60 * 1000

    @staticmethod
    def _meal_macros(p: dict[str, Any]) -> tuple[float | None, ...]:
        """(kcal, carbs, protein, fiber) from a meal payload — None when the
        record carries no value for that macro. Missing is NOT zero: a record
        without a fiber field says nothing about fiber, and rendering it as
        0g makes the LLM claim a gap that may not exist.

        Production payloads nest macros under ``nutrition`` (calories,
        proteins, carbohydrates, fiber); some sources use flat keys.
        """
        n = p.get("nutrition") or {}

        def pick(*candidates: tuple[dict, str]) -> float | None:
            for src, key in candidates:
                v = src.get(key)
                if isinstance(v, (int, float)):
                    return float(v)
            return None

        return (
            pick((n, "calories"), (p, "calories")),
            pick((n, "carbohydrates"), (p, "carbs_g")),
            pick((n, "proteins"), (p, "protein_g")),
            pick((n, "fiber"), (p, "fiber_g")),
        )

    def _meal_totals_section(
        self,
        meals: list[dict[str, Any]],
        *,
        trigger: EventTrigger | None,
        trigger_record: dict[str, Any] | None,
    ) -> str | None:
        """Pre-computed meal totals the LLM can trust instead of adding
        numbers itself.

        * Cron sweep: totals across today's fetched meals.
        * Meal event: totals for THIS SITTING — the trigger meal plus any
          co-logged items within 90 minutes of it.
        """
        def fmt(label: str, items: list[dict[str, Any]]) -> str:
            names = (" kcal", "g carbs", "g protein", "g fiber")
            sums = [0.0] * 4
            counts = [0] * 4
            for m in items:
                for i, v in enumerate(self._meal_macros(m)):
                    if v is not None:
                        sums[i] += v
                        counts[i] += 1
            parts: list[str] = []
            partial = False
            for i, unit in enumerate(names):
                if counts[i] == 0:
                    continue  # no record has this macro — unknown, not zero
                prefix = "at least " if counts[i] < len(items) else ""
                partial = partial or counts[i] < len(items)
                parts.append(f"{prefix}{sums[i]:.0f}{unit}")
            if not parts:
                return f"{label}: {len(items)} items — no macro data recorded"
            note = " (some items lack full macro data)" if partial else ""
            return f"{label}: {len(items)} items — approx {', '.join(parts)}{note}"

        if trigger == EventTrigger.MEAL_LOGGED and trigger_record is not None:
            t0 = trigger_record.get("start_time")
            if not isinstance(t0, (int, float)):
                return None
            sitting = [trigger_record] + [
                m for m in meals
                if isinstance(m.get("start_time"), (int, float))
                and abs(m["start_time"] - t0) <= self._SITTING_WINDOW_MS
            ]
            if len(sitting) < 2:
                return None  # single-item meal — the record speaks for itself
            return (
                "## THIS SITTING — trigger item + "
                f"{len(sitting) - 1} co-logged item(s) within 90 min. COMPUTED "
                "TOTALS, judge the meal by these (do not re-add numbers "
                "yourself):\n- " + fmt("Combined sitting", sitting)
            )

        if trigger is None and meals:
            return (
                "## MEAL TOTALS TODAY — COMPUTED, trust these sums (do not "
                "re-add numbers yourself):\n- " + fmt("Total so far", meals)
            )
        return None

    # Derived from the canonical memory schema — a goal key added to the
    # fact extractor must appear in the monitor's goals section automatically.
    from lib.ai_foundation.agents.core.fact_extractor import CANONICAL_MEMORY_KEYS as _CMK
    _GOAL_KEYS = frozenset(k for k, v in _CMK.items() if v["category"] == "goal")
    del _CMK

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
        except Exception as exc:
            # Degrades to a scan without facts — must be visible, not silent.
            logger.warning("Failed to load facts for %s: %s", patient_id, exc)
            return ""

    async def _get_care_intents(self, patient_id: str) -> list[dict]:
        if not self._care_intents:
            return []
        try:
            return await self._care_intents.get_active_context(patient_id)
        except Exception as exc:
            # Degrades to a scan without care-team context — visible, not silent.
            logger.warning("Failed to load care intents for %s: %s", patient_id, exc)
            return []

    @staticmethod
    def _format_care_intents_section(intents: list[dict]) -> str:
        """Attributed prompt section. Attribution is the lever: "Dr. Mehta
        asked us to check" lands where "the app suggests" doesn't."""
        if not intents:
            return ""
        lines = []
        for ci in intents:
            cond = f" (when: {ci['trigger_condition']})" if ci.get("trigger_condition") else ""
            adherence = (
                f"\n  recent adherence: {ci['adherence_hint']}"
                if ci.get("adherence_hint")
                else ""
            )
            lines.append(
                f"- [{ci['author_name']}, {ci['author_role']}] "
                f"{ci['original_text']}{cond}{adherence}"
            )
        return (
            "CARE TEAM FOCUS — instructions from this patient's providers. "
            "Weave these into insights where today's data makes them relevant, "
            "attributing the provider by name. When adherence shows repeated "
            "misses, gently explore what's making it hard — never scold. "
            "NEVER invent an instruction that is not listed:\n" + "\n".join(lines)
        )

    async def _record_adherence(
        self, patient_id: str, intents: list[dict], data_text: str, scan_date: str, scan_label: str,
    ) -> None:
        """Morning-cron only: judge each intent against the completed previous
        day and upsert the verdicts. Failure never touches the scan."""
        try:
            from datetime import date as _date

            from lib.ai_foundation.care_intents.adherence import evaluate_adherence

            verdicts = await evaluate_adherence(
                self.gateway,
                intents=intents,
                day_data_text=data_text,
                day_label=scan_label,
            )
            await self._care_intents.record_adherence(
                verdicts,
                patient_id=patient_id,
                event_date=_date.fromisoformat(scan_date),
            )
            logger.info(
                "care_intents.adherence_recorded | patient=%s date=%s verdicts=%s",
                patient_id[:8], scan_date,
                {v["care_intent_id"][:8]: v["status"] for v in verdicts},
            )
        except Exception as exc:
            logger.warning("Adherence evaluation failed for %s: %s", patient_id, exc)

    async def _load_medications(self, patient_id: str) -> str:
        """Load all medications from Qdrant (no date filter — persistent context)."""
        try:
            results = await self._qdrant.retrieve_filtered(
                RetrievalRequest(
                    query="",  # required field — omitting it made this a silent no-op
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
        except Exception as exc:
            # Degrades to a scan without meds context — must be visible, not silent.
            logger.warning("Failed to load medications for %s: %s", patient_id, exc)
        return ""

    async def _load_metabolic_profile(self, patient_id: str) -> str:
        if not self._metabolic:
            return ""
        try:
            profile = await self._metabolic.risk_profile(patient_id)
            parts = []
            if profile.get("mmiq_tier"):
                parts.append(f"Metabolic phenotype: {profile['mmiq_tier']}")
            if profile.get("mmiq_driver"):
                parts.append(f"Primary CGM driver: {profile['mmiq_driver']}")
            bmiq = profile.get("bmiq")
            if bmiq:
                parts.append(f"Body composition (BMIQ): {bmiq}")
            wt = profile.get("weight_trend")
            if wt:
                parts.append(f"Weight trend: {wt}")
            flags = profile.get("safety_flags")
            if flags:
                parts.append(f"Safety flags: {flags}")
            if parts:
                return "Metabolic Engine Profile:\n" + "\n".join(f"- {p}" for p in parts)
        except Exception:
            logger.debug("metabolic profile unavailable for %s", patient_id, exc_info=True)
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
        trigger_record: dict[str, Any] | None = None,
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
                suggested_query="How am I doing overall?",
            )], None

        context_parts: list[str] = []
        if trigger is not None:
            # Trigger event section — the specific record the LLM must react to.
            # For triggers with a fetchable record (meal, symptom) we show the
            # full Qdrant payload. For others (CGM threshold, medication missed)
            # the anchor metadata is the event data itself.
            if trigger_record is not None:
                event_text = trigger_record.get("text_repr") or self._format_record(trigger_record)
                # Small models weight nearby instructions most: when the item is
                # part of a multi-item sitting, say so INSIDE the trigger block,
                # not only in the distant system prompt.
                if data_text and "## THIS SITTING" in data_text:
                    event_text += (
                        "\n\nIMPORTANT: this item is one part of a multi-item sitting — "
                        "see the computed THIS SITTING totals below. React to the WHOLE "
                        "sitting by those totals: praise it if the combined meal is "
                        "genuinely good, flag it if it is heavy — but never judge this "
                        "item alone."
                    )
                context_parts.append(
                    f"# TRIGGER EVENT — this is what just happened, your insight MUST be about this:\n{event_text}"
                )
            else:
                anchor_text = (
                    "\n".join(f"- {k}: {v}" for k, v in anchor.model_dump().items())
                    if anchor is not None
                    else "(none)"
                )
                context_parts.append(
                    f"# TRIGGER EVENT — this is what just happened, your insight MUST be about this:\n{anchor_text}"
                )
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
        # Per-patient values (name, greeting) ride in the USER message, not the
        # system prompt — keeps the system prompt byte-identical across a whole
        # scan batch so provider prompt caching can reuse it patient-to-patient.
        if trigger is not None:
            template_str = self._get_event_scan_prompt_template()
            system_prompt = Template(template_str).safe_substitute(
                trigger_label=TRIGGER_LABELS[trigger],
                categories=LLM_INSIGHT_CATEGORIES_PROMPT,
            )
            patient_line = f"PATIENT: {patient_name}"
        else:
            template_str = self._get_scan_prompt_template()
            system_prompt = Template(template_str).safe_substitute(
                scan_label=scan_label,
                scan_period=scan_period,
                categories=LLM_INSIGHT_CATEGORIES_PROMPT,
            )
            patient_line = f"PATIENT: {patient_name}. GREETING: '{greeting}'"

        try:
            scan_insights, llm_meta = await self.gateway.extract(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n\n".join([patient_line, *context_parts])},
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
            # Stay silent in BOTH modes: a content-free "open the app" push
            # helps nobody, and recording one dedup-blocks real insights for
            # 24h. ERROR (not warning) so provider outages surface in ops
            # alerting; the next scan retries with real content.
            mode = trigger.value if trigger is not None else "cron"
            logger.error("Insight analysis failed (%s) — skipping, no fallback push: %s",
                         mode, exc, exc_info=True)
            return [], None

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
        # Name/greeting in the USER message — system prompt stays byte-identical
        # across the batch (see _llm_scan_insights).
        system_prompt = Template(self._get_brief_prompt_template()).safe_substitute(
            scan_label=scan_label,
            scan_period=scan_period,
            categories=LLM_INSIGHT_CATEGORIES_PROMPT,
        )
        patient_line = f"PATIENT: {patient_name}. GREETING: '{greeting}'"

        try:
            brief, llm_meta = await self.gateway.extract(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n\n".join([patient_line, *context_parts])},
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
            # Same policy as _llm_scan_insights: no content-free fallback push.
            logger.error("Daily brief analysis failed — skipping, no fallback push: %s",
                         exc, exc_info=True)
            return [], None

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

                should_send, escalated_severity, consecutive_days = check
                if should_send:
                    escalated = InsightSeverity(escalated_severity)
                    if SEVERITY_RANK[escalated.value] > SEVERITY_RANK[insight.severity.value]:
                        insight.severity = escalated
                    # Stash the streak so record_insight can skip re-deriving
                    # it with another find_one (the tracker computed it here).
                    insight.data["consecutive_days"] = consecutive_days
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
        entity_type: str | None = None,
        entity_id: str | None = None,
        event_time: str | None = None,
        translation: dict | None = None,
    ) -> None:
        """Record that an insight was actually sent as a notification.

        For daily briefs, records each covered category so afternoon/evening
        scans correctly dedup against content already mentioned in the brief.
        """
        if not self._insight_tracker:
            return

        trigger_val = trigger or "cron"
        is_event = trigger_val != "cron"

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
                entity_type=entity_type,
                entity_id=entity_id,
                translation=translation,
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
            # Event scans are streak-1 by definition; cron scans reuse the
            # value _filter_insights computed via should_send.
            consecutive_days=1 if is_event else insight.data.get("consecutive_days"),
            entity_type=entity_type,
            entity_id=entity_id,
            event_time=event_time,
            translation=translation,
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
