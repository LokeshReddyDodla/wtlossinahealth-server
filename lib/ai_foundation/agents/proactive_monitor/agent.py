"""
Proactive Monitor Agent — background health monitoring.

Scans patient data periodically, detects noteworthy patterns, and publishes
insights via the EventBus. Designed to run as a background task (arq cron)
rather than responding to user queries.

Pipeline:
    1. Fetch patient's recent data (CompositeRetriever)
    2. Load patient memory facts (MemoryStore)
    3. Analyze with LLM (ModelGateway.extract → list[HealthInsight])
    4. Filter duplicates against recent insights
    5. Publish insights to EventBus
    6. Record trace for observability
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from lib.ai_foundation.agents.base import BaseAgent
from lib.ai_foundation.agents.state import AgentInput, AgentOutput
from lib.ai_foundation.events.schemas import HealthEvent
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.retrieval.base import RetrievalRequest

from .contracts import (
    BatchScanResult,
    HealthInsight,
    InsightCategory,
    InsightSeverity,
    ScanResult,
)

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


class _InsightList(BaseModel):
    """Wrapper for LLM extraction — list of insights."""
    insights: list[HealthInsight] = Field(default_factory=list)


class ProactiveMonitorAgent(BaseAgent):
    """Background health monitor that detects patterns and sends notifications.

    Unlike the HealthQueryAgent which responds to user queries, this agent
    runs on a schedule (or triggered by events) and proactively surfaces
    insights.

    Example::

        monitor = ProactiveMonitorAgent(
            gateway=gateway, memory=memory, retriever=retriever,
            event_bus=event_bus, prompts=prompts,
        )

        # Scan a single patient
        result = await monitor.scan_patient("patient_123")
        for insight in result.insights:
            print(f"[{insight.severity}] {insight.title}: {insight.body}")

        # Scan a batch (for cron jobs)
        batch = await monitor.scan_batch(["p1", "p2", "p3"])
        print(f"Scanned {batch.scanned}, found {batch.total_insights} insights")
    """

    agent_id = "proactive_monitor"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._prompts_registered = False

    # -- Public API ---------------------------------------------------------

    async def scan_patient(self, patient_id: str) -> ScanResult:
        """Scan a single patient's recent data for noteworthy patterns."""
        start = time.perf_counter()

        try:
            # 1. Fetch recent data
            data = await self._fetch_patient_data(patient_id)
            if not data:
                return ScanResult(
                    patient_id=patient_id,
                    data_available=False,
                    scan_duration_ms=int((time.perf_counter() - start) * 1000),
                )

            # 2. Load memory facts
            facts = await self._load_patient_facts(patient_id)

            # 3. Analyze with LLM
            insights = await self._analyze(patient_id, data, facts)

            # 4. Publish insights
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

    async def scan_batch(self, patient_ids: list[str]) -> BatchScanResult:
        """Scan multiple patients. Used by cron jobs."""
        start = time.perf_counter()
        batch = BatchScanResult(total_patients=len(patient_ids))

        for pid in patient_ids:
            result = await self.scan_patient(pid)
            batch.results.append(result)
            batch.scanned += 1
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

    async def _fetch_patient_data(self, patient_id: str) -> list[dict[str, Any]]:
        """Fetch recent health data for analysis."""
        if not self.retriever:
            return []

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

        request = RetrievalRequest(
            query="recent health summary",
            patient_ids=[patient_id],
            data_types=["cgm_range_stats", "cgm_summary_stats", "meal", "fitness_overview"],
            date_start=week_ago,
            date_end=today,
            limit=30,
        )

        result = await self.retriever.retrieve(request)

        return [item.payload for item in result.items]

    async def _load_patient_facts(self, patient_id: str) -> list[dict]:
        """Load patient memory facts."""
        if not self.memory:
            return []
        try:
            facts = await self.memory.get_patient_facts(patient_id)
            return [f.model_dump(mode="json") for f in facts]
        except Exception:
            return []

    async def _analyze(
        self,
        patient_id: str,
        data: list[dict[str, Any]],
        facts: list[dict],
    ) -> list[HealthInsight]:
        """Use LLM to detect noteworthy patterns in the data."""
        self._ensure_prompts()

        scan_prompt = self.prompts.get("pm_scan_analysis").body

        # Build compact data summary for the LLM
        data_summary = self._build_data_summary(data)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": scan_prompt},
        ]

        if facts:
            compact = [f"- {f['key']}: {f['value']}" for f in facts[:6]]
            messages.append({
                "role": "system",
                "content": "Patient context:\n" + "\n".join(compact),
            })

        messages.append({
            "role": "user",
            "content": f"Analyze this patient's recent health data and return insights:\n\n{data_summary}",
        })

        result, meta = await self.gateway.extract(
            messages=messages,
            response_model=_InsightList,
            task=ModelTask.CLASSIFICATION,
        )

        # Stamp patient_id on all insights
        for insight in result.insights:
            insight.patient_id = patient_id

        return result.insights

    async def _publish_insight(self, insight: HealthInsight) -> None:
        """Publish an insight to the EventBus for notification delivery."""
        if not self.event_bus:
            return

        await self.event_bus.publish(HealthEvent(
            event_type="proactive_insight",
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
        if "pm_scan_analysis" not in self.prompts:
            self.prompts.register_directory(_PROMPTS_DIR, namespace="proactive_monitor")
        self._prompts_registered = True

    @staticmethod
    def _build_data_summary(data: list[dict[str, Any]]) -> str:
        """Build a compact text summary of the data for the LLM context."""
        by_type: dict[str, list[dict]] = {}
        for item in data:
            dt = item.get("data_type", "unknown")
            by_type.setdefault(dt, []).append(item)

        sections: list[str] = []
        for dt, items in by_type.items():
            sections.append(f"## {dt} ({len(items)} records)")
            # Show first 5 items per type to keep context reasonable
            for item in items[:5]:
                # Remove verbose fields
                compact = {k: v for k, v in item.items() if k not in ("source", "data_type") and v is not None}
                sections.append(f"  {compact}")
            if len(items) > 5:
                sections.append(f"  ... and {len(items) - 5} more")

        return "\n".join(sections) if sections else "No recent health data available."
