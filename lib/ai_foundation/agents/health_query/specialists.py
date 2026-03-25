"""
Domain Specialists — lightweight reasoning workers scoped to health domains.

Each specialist runs a mini agentic loop focused on its domain (glucose, nutrition,
fitness). Specialists are NOT BaseAgent subclasses — they don't handle context loading,
persistence, or streaming. The coordinator handles all of that.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator

from lib.ai_foundation.config import settings
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.streaming.sse import (
    sse_reasoning,
    sse_tool_call,
    sse_tool_result,
)

if TYPE_CHECKING:
    from lib.ai_foundation.agents.health_query.tools import ToolExecutor
    from lib.ai_foundation.models.gateway import ModelGateway

logger = logging.getLogger(__name__)

def _is_no_data(result: str) -> bool:
    """Check if a tool result indicates no data was found.

    Uses the structural NO_DATA_PREFIX sentinel set by ToolExecutor,
    not fragile string matching on natural language.
    """
    from lib.ai_foundation.agents.health_query.tools import NO_DATA_PREFIX
    return result.startswith(NO_DATA_PREFIX)


# ── Domain Configuration ───────────────────────────────────────────────────


@dataclass(frozen=True)
class DomainSpec:
    """Configuration for a health domain specialist."""

    domain: str
    data_types: list[str]
    system_prompt: str


# Pre-built domain specs

_LANE_RULE = (
    "\n\nIMPORTANT RULES:"
    "\n1. You MUST call at least one tool before responding. NEVER assume data exists or doesn't — always check by calling look_up or another tool. You have NO data in your context until you fetch it."
    "\n2. You are ONLY responsible for your domain. Do NOT fetch or discuss data from other domains (other specialists handle those)."
    "\n3. Only use the data_types listed in your tool descriptions."
    "\n4. If tools return no data, say so briefly and stop."
)

GLUCOSE_SPEC = DomainSpec(
    domain="glucose",
    data_types=[
        "cgm_range_stats", "cgm_summary_stats",
        "hypo_event", "hypo_stats", "hyper_event", "hyper_stats",
        "rapid_spike_event", "rapid_spike_stats",
        "rapid_drop_event", "rapid_drop_stats",
        "smbg", "time_period_stats", "agp_point",
    ],
    system_prompt=(
        "You are a GLUCOSE analysis specialist. Your domain: CGM readings, glucose summaries, "
        "hypo/hyper events, spikes, drops, SMBG. Focus on:\n"
        "- Time in Range (TIR), glucose variability (CV%), GMI\n"
        "- Spike patterns: timing, severity, frequency\n"
        "- Hypo/hyper event clustering and triggers\n"
        "- Day-to-day and week-to-week trends\n"
        "- Compare against the patient's OWN baseline, not population norms"
        + _LANE_RULE
    ),
)

NUTRITION_SPEC = DomainSpec(
    domain="nutrition",
    data_types=["meal"],
    system_prompt=(
        "You are a NUTRITION analysis specialist. Your domain: meals only. Focus on:\n"
        "- Meal composition: calories, protein, carbs, fat per meal\n"
        "- Meal timing patterns (late dinners, skipped meals)\n"
        "- Macro distribution and balance\n"
        "- Alignment with patient's dietary preferences and goals\n"
        "- Specific, actionable food recommendations based on their actual data"
        + _LANE_RULE
    ),
)

FITNESS_SPEC = DomainSpec(
    domain="fitness",
    data_types=[
        "fitness_overview", "fitness_activity_distribution",
        "fitness_inactive_periods",
    ],
    system_prompt=(
        "You are a FITNESS and activity specialist. Your domain: activity, steps, exercise only. Focus on:\n"
        "- Daily steps, active minutes, calories burned\n"
        "- Activity patterns and consistency\n"
        "- Sedentary periods and their health impact\n"
        "- Progress toward the patient's activity goals"
        + _LANE_RULE
    ),
)

VITALS_SPEC = DomainSpec(
    domain="vitals",
    data_types=["vital", "profile"],
    system_prompt=(
        "You are a VITALS and body metrics specialist. Your domain: blood pressure, heart rate, "
        "weight, SpO2, profile only. Focus on:\n"
        "- Blood pressure trends (hypertension is common in diabetes and obesity)\n"
        "- Resting heart rate patterns and variability\n"
        "- Weight trends over time — progress toward weight loss goals\n"
        "- BMI trajectory and body composition changes\n"
        "- SpO2 readings if available (sleep apnea risk in obese patients)\n"
        "- Flag concerning trends: rising BP, rapid weight gain, abnormal HR"
        + _LANE_RULE
    ),
)

SLEEP_SPEC = DomainSpec(
    domain="sleep",
    data_types=["sleep"],
    system_prompt=(
        "You are a SLEEP analysis specialist. Your domain: sleep data only. Focus on:\n"
        "- Sleep duration trends (recommended 7-9 hours for metabolic health)\n"
        "- Sleep quality patterns and disturbances\n"
        "- Sleep apnea indicators (very common in obese patients)\n"
        "- Sleep consistency (regular vs irregular schedule)\n"
        "- Flag concerning patterns: chronic short sleep, frequent waking, deteriorating quality"
        + _LANE_RULE
    ),
)

DOCUMENTS_SPEC = DomainSpec(
    domain="documents",
    data_types=["patient_document"],
    system_prompt=(
        "You are a MEDICAL DOCUMENTS specialist. Your domain: lab reports, prescriptions, "
        "clinical notes only. Focus on:\n"
        "- Lab results: HbA1c trends, lipid panel, kidney function (eGFR, creatinine)\n"
        "- Prescription history: medication changes, dosage adjustments\n"
        "- Clinical notes: doctor observations, treatment plans\n"
        "- Test results: thyroid, liver function, vitamin levels\n"
        "- Track HbA1c progression over time (the gold standard for diabetes control)\n"
        "- Flag overdue labs or missing follow-ups based on last test dates"
        + _LANE_RULE
    ),
)

DEFAULT_SPECS: dict[str, DomainSpec] = {
    "glucose": GLUCOSE_SPEC,
    "nutrition": NUTRITION_SPEC,
    "fitness": FITNESS_SPEC,
    "vitals": VITALS_SPEC,
    "sleep": SLEEP_SPEC,
    "documents": DOCUMENTS_SPEC,
}


# ── Specialist Findings ───────────────────────────────────────────────────


@dataclass
class SpecialistFindings:
    """Output from a specialist's investigation."""

    domain: str
    findings: str
    tool_calls_used: int = 0
    data_gathered: list[str] = field(default_factory=list)
    cost: float = 0.0


# ── Specialist ─────────────────────────────────────────────────────────────


class Specialist:
    """A domain-focused investigator that runs a mini reasoning loop.

    Usage::

        specialist = Specialist(domain_spec=GLUCOSE_SPEC, gateway=gw, tool_executor=te)
        findings = await specialist.investigate(
            messages=base_messages,
            patient_ids=["p123"],
            max_rounds=3,
            model_id="gpt-4.1-mini",
        )
    """

    def __init__(
        self,
        *,
        domain_spec: DomainSpec,
        gateway: ModelGateway,
        tool_executor: ToolExecutor,
    ) -> None:
        self._spec = domain_spec
        self._gateway = gateway
        self._tools = tool_executor

    @property
    def domain(self) -> str:
        return self._spec.domain

    async def investigate(
        self,
        *,
        messages: list[dict[str, Any]],
        patient_ids: list[str],
        max_rounds: int = 3,
        model_id: str,
    ) -> SpecialistFindings:
        """Run a domain-scoped investigation."""
        # Add domain-specific system prompt
        specialist_messages: list[dict[str, Any]] = list(messages)
        specialist_messages.insert(1, {
            "role": "system",
            "content": self._spec.system_prompt,
        })

        tool_schemas = self._tools.get_schemas_for_domain(self._spec.domain)
        findings_parts: list[str] = []
        total_tools = 0
        total_cost = 0.0
        seen_calls: set[str] = set()

        for round_num in range(1, max_rounds + 1):
            response = await self._gateway.complete_with_tools(
                messages=specialist_messages,
                tools=tool_schemas,
                task=ModelTask.CLASSIFICATION,
                model_id=model_id,
                timeout=settings.REASONING_TIMEOUT_SECONDS,
            )
            total_cost += response.usage.cost.total_cost if response.usage.cost else 0

            if not response.has_tool_calls:
                if response.content:
                    findings_parts.append(response.content)
                break

            # Build assistant tool call message
            specialist_messages.append({
                "role": "assistant",
                "content": response.content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function_name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ],
            })

            # Partition: new vs duplicate
            to_execute: list[tuple[str, dict, str]] = []
            duplicate_ids: list[str] = []
            for tc in response.tool_calls:
                call_key = f"{tc.function_name}:{json.dumps(tc.arguments, sort_keys=True)}"
                if call_key not in seen_calls:
                    seen_calls.add(call_key)
                    to_execute.append((tc.function_name, tc.arguments, tc.id))
                else:
                    duplicate_ids.append(tc.id)

            # Execute non-duplicates in parallel
            if to_execute:
                results = await self._tools.execute_parallel(
                    [(name, args) for name, args, _ in to_execute],
                    patient_ids,
                )
                total_tools += len(to_execute)

                for (name, args, tc_id), result_text in zip(to_execute, results):
                    findings_parts.append(result_text)
                    specialist_messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_text,
                    })

                # Early exit: if all results are "no data", stop investigating
                if all(_is_no_data(r) for r in results):
                    for tc_id in duplicate_ids:
                        specialist_messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": "Already fetched. Try different parameters.",
                        })
                    break

            # Every tool_call_id MUST have a tool result — add dup warnings
            for tc_id in duplicate_ids:
                specialist_messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": "Already fetched. Try different parameters.",
                })

        return SpecialistFindings(
            domain=self._spec.domain,
            findings="\n\n".join(findings_parts),
            tool_calls_used=total_tools,
            data_gathered=[f[:200] for f in findings_parts],
            cost=total_cost,
        )

    async def investigate_stream(
        self,
        *,
        messages: list[dict[str, Any]],
        patient_ids: list[str],
        max_rounds: int = 3,
        model_id: str,
    ) -> AsyncIterator[str]:
        """Streaming version that yields SSE events during investigation."""
        specialist_messages: list[dict[str, Any]] = list(messages)
        specialist_messages.insert(1, {
            "role": "system",
            "content": self._spec.system_prompt,
        })

        tool_schemas = self._tools.get_schemas_for_domain(self._spec.domain)
        seen_calls: set[str] = set()

        for round_num in range(1, max_rounds + 1):
            response = await self._gateway.complete_with_tools(
                messages=specialist_messages,
                tools=tool_schemas,
                task=ModelTask.CLASSIFICATION,
                model_id=model_id,
                timeout=settings.REASONING_TIMEOUT_SECONDS,
            )

            if not response.has_tool_calls:
                if response.content:
                    yield sse_reasoning(round_num, f"[{self._spec.domain}] {response.content}")
                break

            if response.content:
                yield sse_reasoning(round_num, f"[{self._spec.domain}] {response.content}")

            specialist_messages.append({
                "role": "assistant",
                "content": response.content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function_name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ],
            })

            to_execute: list[tuple[str, dict, str]] = []
            duplicate_ids: list[str] = []
            for tc in response.tool_calls:
                call_key = f"{tc.function_name}:{json.dumps(tc.arguments, sort_keys=True)}"
                if call_key not in seen_calls:
                    seen_calls.add(call_key)
                    to_execute.append((tc.function_name, tc.arguments, tc.id))
                    yield sse_tool_call(tc.function_name, tc.arguments)
                else:
                    duplicate_ids.append(tc.id)

            if to_execute:
                results = await self._tools.execute_parallel(
                    [(name, args) for name, args, _ in to_execute],
                    patient_ids,
                )
                for (name, args, tc_id), result_text in zip(to_execute, results):
                    lines = result_text.strip().split("\n")
                    summary = lines[0][:200] if lines else "No data"
                    yield sse_tool_result(name, summary)
                    specialist_messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_text,
                    })

                # Early exit: no data means nothing more to investigate
                if all(_is_no_data(r) for r in results):
                    for tc_id in duplicate_ids:
                        specialist_messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": "Already fetched. Try different parameters.",
                        })
                    break

            # Every tool_call_id MUST have a tool result
            for tc_id in duplicate_ids:
                specialist_messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": "Already fetched. Try different parameters.",
                })
