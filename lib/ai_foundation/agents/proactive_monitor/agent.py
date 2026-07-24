"""
Proactive Monitor Agent — detects when to reach out, delegates the reasoning.

The monitor does not think: for both event triggers and the scheduled cron
digest it deterministically frames the moment (see event_framing) and calls
HealthQueryAgent.run_proactive — the one brain investigates the patient's data,
decides whether the moment is worth a push, and writes the copy. Category and
severity are set here from the trigger, never by the model.

Morning cron additionally records care-intent adherence (a separate scorer that
feeds the provider view — not narration).
"""

from __future__ import annotations

from uuid import uuid4

import asyncio
import inspect
import logging
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from lib.ai_foundation.agents.base import BaseAgent
from lib.ai_foundation.agents.health_query.contracts import HealthDataType
from lib.ai_foundation.agents.state import AgentInput, AgentOutput
from lib.ai_foundation.retrieval.base import RetrievalRequest

from .scheduling import DEFAULT_TIMEZONE
from lib.ai_foundation.agents.core.refs import Ref, RefType, resolve_refs
from lib.ai_foundation.agents.health_query.reasoning_engine import ReasoningTier
from .event_framing import (
    classify_event,
    classify_glucose_value,
    event_ref,
    frame_cron,
    frame_event,
    is_wired,
    severity_tier,
    trigger_tier,
)
from .contracts import (
    BatchScanResult,
    EventTrigger,
    HealthInsight,
    InsightCategory,
    InsightSeverity,
    ScanResult,
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
    """Background health monitor: detects when to reach out, then delegates the
    reasoning and copy to the one brain (HealthQueryAgent.run_proactive).

    The monitor owns only deterministic concerns — framing the moment, the
    reasoning tier, and the insight's category/severity — plus morning
    care-intent adherence scoring. It does not narrate.

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
        metabolic_service: Any | None = None,
        care_intents: Any | None = None,
        daily_tasks: Any | None = None,
        health_agent: Any | None = None,
    ) -> None:
        super().__init__(gateway=gateway, prompts=prompts, event_bus=event_bus, memory=memory)
        self._qdrant = qdrant
        # HealthQueryAgent — the reasoning + copy for every proactive insight.
        # None only in tests that never reach narration.
        self._health_agent = health_agent
        self._insight_tracker = insight_tracker
        self._metabolic = metabolic_service
        # Duck-typed reader with get_active_context(patient_id) -> list[dict]
        # (CareIntentService in production) — ai_foundation stays import-free
        # of the service layer.
        self._care_intents = care_intents
        # Duck-typed reader with get_active_nudges(patient_id) -> list[str]
        # (GamificationService) — the day's other proactive nudges, so this
        # brain coordinates with them instead of duplicating them.
        self._daily_tasks = daily_tasks

    async def _classify(
        self, patient_id: str, trigger: EventTrigger, anchor: TriggerAnchor,
    ) -> tuple[InsightCategory, InsightSeverity, ReasoningTier]:
        """Deterministic category + severity + tier for an event. SMBG is graded
        by its actual reading (a finger-stick low is as serious as a sensor low);
        if the value can't be read, fall back to the trigger's fixed class."""
        if trigger is EventTrigger.SMBG_LOGGED:
            value = await self._smbg_value(patient_id, anchor)
            if value is not None:
                category, severity = classify_glucose_value(value)
                return category, severity, severity_tier(severity)
        category, severity = classify_event(trigger, anchor)
        return category, severity, trigger_tier(trigger, anchor)

    async def _smbg_value(self, patient_id: str, anchor: TriggerAnchor) -> float | None:
        """Look up the logged finger-stick reading (mg/dL) by its id, or None."""
        try:
            resolved = await resolve_refs(
                patient_id=patient_id, refs=[Ref(type=RefType.SMBG, id=anchor.reading_id)],
            )
            payload = resolved[0].payload if resolved else {}
            for key in ("glucose_mgdl", "value", "reading", "glucose_level"):
                v = payload.get(key)
                if isinstance(v, (int, float)):
                    return float(v)
        except Exception as exc:
            logger.warning("smbg value lookup failed for %s: %s", patient_id, exc)
        return None

    async def _event_insight(
        self,
        patient_id: str,
        trigger: EventTrigger,
        anchor: TriggerAnchor,
        *,
        patient_name: str | None = None,
    ) -> ScanResult:
        """Produce a single event insight for a trigger.

        Category + severity are deterministic (never from the model); the brain
        investigates the pinned entity, writes the copy, and may decline to
        notify (empty insights).
        """
        category, severity, tier = await self._classify(patient_id, trigger, anchor)
        ref = event_ref(trigger, anchor)

        start = time.perf_counter()
        narration = await self._health_agent.run_proactive(
            patient_id=patient_id,
            event_summary=frame_event(trigger, anchor, patient_name),
            tier=tier,
            refs=[ref] if ref else None,
        )
        duration = int((time.perf_counter() - start) * 1000)

        if not narration.notify or not narration.body.strip():
            logger.info("proactive: no notification warranted for %s (%s)", patient_id[:8], trigger.value)
            return ScanResult(patient_id=patient_id, insights=[], scan_duration_ms=duration)

        insight = HealthInsight(
            category=category,
            severity=severity,
            title=narration.title.strip() or category.value.replace("_", " ").title(),
            body=narration.body.strip(),
            patient_id=patient_id,
            suggested_query=narration.suggested_query,
            data={"trigger": trigger.value},
        )
        return ScanResult(patient_id=patient_id, insights=[insight], scan_duration_ms=duration)

    async def _cron_narration(
        self, patient_id: str, patient_name: str | None, scan_period: str,
    ) -> list[HealthInsight]:
        """The scheduled daily digest. Returns [] when the brain declines."""
        narration = await self._health_agent.run_proactive(
            patient_id=patient_id,
            event_summary=frame_cron(patient_name, scan_period),
            tier=ReasoningTier.ADVANCED,
        )
        if not narration.notify or not narration.body.strip():
            return []
        return [HealthInsight(
            category=InsightCategory.DAILY_BRIEF,
            severity=InsightSeverity.INFO,
            title=narration.title.strip() or "Your check-in",
            body=narration.body.strip(),
            patient_id=patient_id,
            suggested_query=narration.suggested_query,
            data={"trigger": "cron"},
        )]

    async def scan_patient(
        self,
        patient_id: str,
        patient_name: str | None = None,
        tz_name: str | None = None,
        *,
        trigger: EventTrigger | None = None,
        anchor: TriggerAnchor | None = None,
    ) -> ScanResult:
        """Produce proactive insights for a patient.

        * Event-driven (``trigger`` set) — one insight about the event.
        * Cron sweep (``trigger=None``) — the scheduled digest; morning runs
          also record care-intent adherence for the completed prior day.

        Empty ``insights`` means nothing was worth sending.
        """
        if trigger is not None:
            if anchor is None or not is_wired(trigger):
                return ScanResult(patient_id=patient_id, error=f"unwired trigger {trigger}")
            try:
                return await self._event_insight(patient_id, trigger, anchor, patient_name=patient_name)
            except Exception as exc:
                logger.exception("proactive event failed for %s: %s", patient_id, exc)
                return ScanResult(patient_id=patient_id, error=str(exc))

        start = time.perf_counter()
        try:
            tz = ZoneInfo(tz_name or DEFAULT_TIMEZONE)
            scan_date, scan_label, scan_period = self._scan_window(datetime.now(tz))
            display_name = patient_name or "this patient"

            # Morning sees the completed prior day — the only window where an
            # adherence verdict isn't premature.
            if scan_period == "morning":
                await self._record_morning_adherence(patient_id, display_name, scan_date, scan_label)

            insights = await self._cron_narration(patient_id, display_name, scan_period)
            for ins in insights:
                logger.info(
                    "proactive_monitor.published_insight | patient=%s mode=cron cat=%s severity=%s title=%r",
                    patient_id[:8], ins.category.value, ins.severity.value, ins.title,
                )
            return ScanResult(
                patient_id=patient_id, scan_date=scan_date, insights=insights,
                scan_duration_ms=int((time.perf_counter() - start) * 1000),
                data_available=True,
            )

        except Exception as exc:
            logger.error("Cron scan failed for %s: %s", patient_id, exc, exc_info=True)
            return ScanResult(
                patient_id=patient_id, error=str(exc),
                scan_duration_ms=int((time.perf_counter() - start) * 1000),
                data_available=False,
            )

    async def _record_morning_adherence(
        self, patient_id: str, display_name: str, scan_date: str, scan_label: str,
    ) -> None:
        """Score care-intent adherence for the completed prior day and store the
        verdicts. Failure never blocks the scan. Behavioral intents only —
        watch/passive have no action to score."""
        try:
            care_intents = await self._get_care_intents(patient_id)
            trackable = [
                ci for ci in care_intents
                if ci.get("intent_type") != "watch" and ci.get("cadence") != "passive"
            ]
            if not trackable:
                return
            facts_text = await self._load_facts(patient_id)
            data_text, _ = await self._fetch_patient_data(
                patient_id=patient_id, patient_name=display_name, scan_date=scan_date,
                data_types=_SCAN_DATA_TYPES, trigger=None, exclude_record=None,
            )
            await self._record_adherence(
                patient_id, trackable, data_text, scan_date, scan_label, facts_text=facts_text,
            )
        except Exception as exc:
            logger.warning("morning adherence failed for %s: %s", patient_id, exc)

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
            scan_date=scan_date,
        )
        if totals:
            # First section, right under the trigger block — sitting totals are
            # the frame everything else must be read in.
            sections.insert(0, totals)

        if trigger is not None:
            header = "# Supporting Context\n"
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
        scan_date: str,
    ) -> str | None:
        """Pre-computed meal totals the LLM can trust instead of adding
        numbers itself.

        The day total is scoped to meals whose ``meal_date`` equals
        ``scan_date`` (the reported local day). Event scans fetch two days of
        meals for glucose context; without this scope the LLM sums both days
        and reports the inflated figure as "today". Matching on the stored
        local date also sidesteps the UTC day-boundary bleed in the fetch.

        * Any scan: the day total for ``scan_date``.
        * Meal event: additionally the THIS SITTING total — the trigger meal
          plus any co-logged items within 90 minutes of it.
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

        blocks: list[str] = []

        if trigger == EventTrigger.MEAL_LOGGED and trigger_record is not None:
            t0 = trigger_record.get("start_time")
            if isinstance(t0, (int, float)):
                sitting = [trigger_record] + [
                    m for m in meals
                    if isinstance(m.get("start_time"), (int, float))
                    and abs(m["start_time"] - t0) <= self._SITTING_WINDOW_MS
                ]
                if len(sitting) >= 2:
                    blocks.append(
                        "## THIS SITTING — trigger item + "
                        f"{len(sitting) - 1} co-logged item(s) within 90 min. "
                        "COMPUTED TOTALS, judge the meal by these (do not re-add "
                        "numbers yourself):\n- " + fmt("Combined sitting", sitting)
                    )

        # Day total scoped to the reported local day, for the cron sweep and
        # meal events (where "intake so far today" is a natural reaction).
        # Non-meal events are barred from daily summaries by the prompt, so no
        # day total is offered there. The trigger meal is excluded from `meals`
        # upstream, so fold it back in when it belongs to this day.
        emit_day_total = trigger is None or trigger == EventTrigger.MEAL_LOGGED
        todays = [m for m in meals if m.get("meal_date") == scan_date]
        if (
            trigger_record is not None
            and trigger_record.get("meal_date") == scan_date
        ):
            todays = [trigger_record] + todays
        if emit_day_total and todays:
            blocks.append(
                f"## MEALS ON {scan_date} — COMPUTED day total, the ONLY "
                "authoritative daily figure. Trust this; never sum meal records "
                "yourself, and never report an earlier day's macros as today:\n- "
                + fmt(f"Day total ({scan_date})", todays)
            )

        return "\n\n".join(blocks) or None

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
        """Care-team intents as a prompt section, each attributed to its
        author (the responder must name the provider, not say "the app")."""
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
        facts_text: str = "",
    ) -> None:
        """Morning-cron only: judge each intent against the completed previous
        day and upsert the verdicts. Failure never touches the scan."""
        try:
            from datetime import date as _date

            from lib.ai_foundation.care_intents.adherence import evaluate_adherence

            judged_day = _date.fromisoformat(scan_date)
            # An intent created after the judged day can't be missed on it.
            intents = [
                ci for ci in intents
                if not ci.get("created_at") or ci["created_at"][:10] <= scan_date
            ]
            if not intents:
                return
            trace_id = f"trc_{uuid4().hex[:16]}"
            self.gateway.set_langfuse_context(
                session_id=f"adherence:{patient_id}", user_id=patient_id,
            )
            self.gateway.langfuse_trace_input(
                trace_id=trace_id, name="care_intent_adherence", input_text=scan_label,
            )
            verdicts = await evaluate_adherence(
                self.gateway,
                intents=intents,
                day_data_text=data_text,
                day_label=scan_label,
                patient_context=facts_text,
                trace_id=trace_id,
            )
            self.gateway.langfuse_trace_output(
                trace_id=trace_id, output_text=str(verdicts),
            )
            await self._care_intents.record_adherence(
                verdicts,
                patient_id=patient_id,
                event_date=judged_day,
            )
            logger.info(
                "care_intents.adherence_recorded | patient=%s date=%s verdicts=%s",
                patient_id[:8], scan_date,
                {v["care_intent_id"][:8]: v["status"] for v in verdicts},
            )
        except Exception as exc:
            logger.warning("Adherence evaluation failed for %s: %s", patient_id, exc)

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

