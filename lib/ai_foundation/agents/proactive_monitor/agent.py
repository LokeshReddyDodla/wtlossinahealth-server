"""
Proactive Monitor Agent — background health monitoring via ReasoningEngine.

Scans patient data periodically, uses the shared ReasoningEngine + ToolExecutor
to investigate health patterns, and publishes structured insights via the
EventBus. Designed to run as a background task (arq cron) rather than
responding to user queries.

Pipeline:
    1. Load patient context (facts, names)
    2. Run ReasoningEngine with BASIC tier (fast — 2 tool calls max)
    3. Extract structured HealthInsight objects from the analysis
    4. Publish insights to EventBus
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from lib.ai_foundation.agents.base import BaseAgent
from lib.ai_foundation.agents.state import AgentInput, AgentOutput
from lib.ai_foundation.events.schemas import HealthEvent, HealthEventType
from lib.ai_foundation.models.registry import ModelTask

from .contracts import (
    BatchScanResult,
    HealthInsight,
    InsightCategory,
    InsightSeverity,
    ScanInsights,
    ScanResult,
)

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


class ProactiveMonitorAgent(BaseAgent):
    """Background health monitor that detects patterns and sends notifications.

    Unlike the HealthQueryAgent which responds to user queries, this agent
    runs on a schedule (or triggered by events) and proactively surfaces
    insights using the shared ReasoningEngine and ToolExecutor.

    Example::

        monitor = ProactiveMonitorAgent(
            gateway=gateway,
            reasoning_engine=engine,
            tool_executor=tool_executor,
            event_bus=event_bus,
            prompts=prompts,
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
        reasoning_engine: Any,
        tool_executor: Any,
        event_bus: Any | None = None,
        prompts: Any | None = None,
        memory: Any | None = None,
        insight_tracker: Any | None = None,
    ) -> None:
        super().__init__(gateway=gateway, prompts=prompts, event_bus=event_bus, memory=memory)
        self._reasoning_engine = reasoning_engine
        self._tools = tool_executor
        self._insight_tracker = insight_tracker
        self._prompts_registered = False

    # -- Public API ---------------------------------------------------------

    async def scan_patient(
        self,
        patient_id: str,
        patient_name: str | None = None,
    ) -> ScanResult:
        """Scan a single patient's recent data and generate insights."""
        start = time.perf_counter()

        try:
            # 1. Load patient context (facts, names)
            context = await self._load_patient_context(patient_id, patient_name)

            # 2. Use the SAME prompts as health query agent — battle-tested
            self._ensure_prompts()
            system_prompt = self._get_scan_prompt()
            reasoning_prompt = self.prompts.get("hq_reasoning").body
            response_prompt = self.prompts.get("hq_final_response").body

            # 3. Determine scan window based on time of day
            now = datetime.now(timezone.utc)
            hour = now.hour
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            today = now.strftime("%Y-%m-%d")

            if hour < 12:
                # Morning: review yesterday
                scan_msg = (
                    f"Review this patient's health data for yesterday ({yesterday}). "
                    f"Check glucose control, meals logged, and activity. "
                    f"Highlight any concerns (spikes, hypos, missed meals) AND any positives "
                    f"(good glucose control, consistent logging, active day)."
                )
            elif hour < 17:
                # Afternoon: check-in on today
                scan_msg = (
                    f"Check this patient's health data for today ({today}) so far. "
                    f"How is their glucose? Did they log meals? Any activity? "
                    f"Report both concerns and positive observations."
                )
            else:
                # Evening: day wrap-up
                scan_msg = (
                    f"Summarize this patient's day today ({today}). "
                    f"Review glucose, meals, and activity. "
                    f"What went well? What needs attention? Give a balanced summary."
                )
            date_types = ["cgm_summary_stats", "meal", "fitness_overview"]

            from lib.ai_foundation.agents.health_query.reasoning_engine import ReasoningTier

            result = await self._reasoning_engine.reason(
                user_message=scan_msg,
                system_prompt=system_prompt,
                reasoning_prompt=reasoning_prompt,
                response_prompt=response_prompt,
                context=context,
                patient_ids=[patient_id],
                tier=ReasoningTier.BASIC,
                intent_data_types=date_types,
                patient_names={patient_id: patient_name} if patient_name else None,
            )

            # 4. Extract structured insights from the text response
            insights = await self._extract_insights(
                result.response, patient_id, patient_name,
            )

            # 5. Dedup + escalation via InsightTracker
            insights = await self._filter_insights(patient_id, insights)

            # 6. Publish insights via EventBus
            for insight in insights:
                await self._publish_insight(insight)

            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ScanResult(
                patient_id=patient_id,
                insights=insights,
                scan_duration_ms=elapsed_ms,
            )

        except Exception as exc:
            logger.error("Scan failed for patient %s: %s", patient_id, exc)
            return ScanResult(
                patient_id=patient_id,
                error=str(exc),
                scan_duration_ms=int((time.perf_counter() - start) * 1000),
            )

    async def scan_batch(
        self,
        patient_ids: list[str],
        patient_names: dict[str, str] | None = None,
    ) -> BatchScanResult:
        """Scan multiple patients. Runs sequentially to avoid overwhelming the LLM."""
        start = time.perf_counter()
        names = patient_names or {}
        batch = BatchScanResult(total_patients=len(patient_ids))

        for pid in patient_ids:
            try:
                result = await self.scan_patient(pid, names.get(pid))
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

    async def _load_patient_context(
        self, patient_id: str, patient_name: str | None,
    ):
        """Build a minimal AgentContext for the scan."""
        from lib.ai_foundation.agents.health_query.context_loader import AgentContext

        facts: list[dict] = []
        if self.memory:
            try:
                raw_facts = await self.memory.get_patient_facts(patient_id)
                facts = [f.model_dump(mode="json") for f in raw_facts[:6]]
            except Exception:
                pass

        names = {patient_id: patient_name} if patient_name else {}
        return AgentContext(
            facts=facts,
            history=[],
            thread_summary=None,
            patient_names=names,
        )

    async def _extract_insights(
        self,
        analysis_text: str,
        patient_id: str,
        patient_name: str | None,
    ) -> list[HealthInsight]:
        """Extract structured HealthInsight objects from the reasoning text."""
        all_categories = ", ".join(c.value for c in InsightCategory)
        try:
            scan_insights, _ = await self.gateway.extract(
                messages=[
                    {"role": "system", "content": (
                        "Extract structured health insights from this analysis. "
                        "Include BOTH concerns AND positive findings. "
                        "ONLY create insights backed by real data in the analysis. "
                        "If the analysis says no data was found or a SYSTEM ERROR occurred, "
                        "return zero insights.\n\n"
                        "For each insight:\n"
                        "- title: SHORT push notification title, max 45 characters\n"
                        "- body: notification text using patient name, max 180 characters\n"
                        f"- category: one of {all_categories}\n"
                        "- severity: info (positive/FYI), attention (worth noting), "
                        "warning (needs attention), alert (urgent)\n"
                        "- suggested_query: a follow-up question the patient could ask"
                    )},
                    {"role": "user", "content": analysis_text},
                ],
                response_model=ScanInsights,
                task=ModelTask.CLASSIFICATION,
            )
            # Stamp patient_id on all insights
            for insight in scan_insights.insights:
                insight.patient_id = patient_id
            return scan_insights.insights
        except Exception as exc:
            logger.warning("Insight extraction failed: %s", exc)
            return []

    async def _filter_insights(
        self,
        patient_id: str,
        insights: list[HealthInsight],
    ) -> list[HealthInsight]:
        """Filter insights through dedup + escalation via InsightTracker."""
        if not self._insight_tracker:
            return insights

        filtered: list[HealthInsight] = []
        for insight in insights:
            try:
                should_send, escalated_severity = await self._insight_tracker.should_send(
                    patient_id, insight.category.value,
                )
                if should_send:
                    # Update severity based on escalation
                    if escalated_severity != "info":
                        insight.severity = InsightSeverity(escalated_severity)
                    filtered.append(insight)
                    await self._insight_tracker.record(
                        patient_id,
                        insight.category.value,
                        insight.severity.value,
                        insight.body,
                    )
                else:
                    logger.debug(
                        "Dedup: skipping %s for patient %s (sent recently)",
                        insight.category.value, patient_id,
                    )
            except Exception as exc:
                logger.warning("InsightTracker error for %s: %s", patient_id, exc)
                filtered.append(insight)  # fail-open: send anyway

        return filtered

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

    # -- Helpers ------------------------------------------------------------

    def _ensure_prompts(self) -> None:
        if self._prompts_registered or not self.prompts:
            return
        # Load proactive monitor prompts (for system prompt)
        if "pm_scan_system" not in self.prompts:
            self.prompts.register_directory(_PROMPTS_DIR, namespace="proactive_monitor")
        # Load health query prompts (for reasoning + response — battle-tested)
        hq_prompts_dir = Path(__file__).parent.parent / "health_query" / "prompts"
        if "hq_reasoning" not in self.prompts and hq_prompts_dir.is_dir():
            self.prompts.register_directory(hq_prompts_dir, namespace="health_query")
        self._prompts_registered = True

    def _get_scan_prompt(self) -> str:
        """Get the system prompt for scanning with current time."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        template = self.prompts.get("pm_scan_system")
        return template.render(current_time=now)
