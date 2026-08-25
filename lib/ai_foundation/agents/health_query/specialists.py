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
from lib.ai_foundation.models.gateway import safe_cost
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.streaming.sse import (
    sse_reasoning,
    sse_tool_call,
    sse_tool_result,
)

from lib.ai_foundation.agents.health_query.tools import is_no_data

if TYPE_CHECKING:
    from lib.ai_foundation.agents.health_query.tools import ToolExecutor
    from lib.ai_foundation.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


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
    "\n5. When you find notable events (spikes, drops, anomalies), include exact timing (date and time) when available so other specialists can cross-reference."
)

def _domain_data_types(spec_key: str, *extra: str) -> list[str]:
    """Derive a specialist's data types from contracts.DOMAIN_MAPPING —
    the routing tables are the single source of truth. A hand-typed list
    here silently strands any HealthDataType added to a domain later
    (the specialist's scoped tools can only expose spec.data_types).
    ``extra``: deliberate additions beyond the domain mapping."""
    from lib.ai_foundation.agents.health_query.contracts import (
        DOMAIN_MAPPING,
        _DOMAIN_TO_SPECIALIST,
    )

    types: list[str] = []
    for domain, key in _DOMAIN_TO_SPECIALIST.items():
        if key == spec_key:
            types.extend(dt.value for dt in DOMAIN_MAPPING[domain])
    types.extend(t for t in extra if t not in types)
    return types


GLUCOSE_SPEC = DomainSpec(
    domain="glucose",
    data_types=_domain_data_types("glucose"),
    system_prompt=(
        "You are a GLUCOSE analysis specialist. Your domain: CGM readings, glucose summaries, "
        "hypo/hyper events, spikes, drops, SMBG. Focus on:\n"
        "- Time in Range (TIR), glucose variability (CV%), GMI\n"
        "- Spike patterns: timing, severity, frequency\n"
        "- Hypo/hyper event clustering and triggers\n"
        "- Day-to-day and week-to-week trends\n"
        "- Compare against the patient's OWN baseline, not population norms\n"
        "- When reporting spikes or unusual readings, note exact time when available — helps correlate with meals and activity\n"
        "- Consider the patient's medications when analyzing glucose. Metformin lowers fasting glucose. "
        "GLP-1 agonists reduce appetite and post-meal spikes. Insulin timing affects when glucose drops. "
        "Don't attribute patterns solely to meals/activity when medication is likely the driver."
        + _LANE_RULE
    ),
)

NUTRITION_SPEC = DomainSpec(
    domain="nutrition",
    data_types=_domain_data_types("nutrition"),
    system_prompt=(
        "You are a NUTRITION & PLANS specialist. Your domains: meals, diet plans, and fitness plans.\n"
        "Focus on:\n"
        "- Meal composition: calories, protein, carbs, fat per meal\n"
        "- Meal timing patterns (late dinners, skipped meals)\n"
        "- Macro distribution and balance\n"
        "- Alignment with patient's dietary preferences and goals\n"
        "- Diet plan targets: compare actual meals against the patient's active diet plan\n"
        "- Fitness plan goals: reference step goals, workout schedules, weekly active minutes\n"
        "- Plan adherence: are they hitting their plan targets? Where are the gaps?\n"
        "- Specific, actionable food recommendations based on their actual data and plan\n"
        "- When reporting meals, note exact time and macros. If the patient has glucose/CGM data, carb content helps correlate with glucose responses; otherwise relate meals to their calorie/protein goals\n"
        "- GLP-1 medications reduce appetite. If the patient is eating less, check if they recently started or increased GLP-1. Expected, not concerning."
        + _LANE_RULE
    ),
)

FITNESS_SPEC = DomainSpec(
    domain="fitness",
    data_types=_domain_data_types("fitness"),
    system_prompt=(
        "You are a FITNESS and activity specialist. Your domain: activity, steps, exercise, and workouts. Focus on:\n"
        "- Daily steps, active minutes, calories burned\n"
        "- Manually-logged workout sessions (type, duration, exercises, intensity)\n"
        "- Activity patterns and consistency across both synced and self-reported data\n"
        "- Sedentary periods and their health impact\n"
        "- Progress toward the patient's activity and step goals\n"
        "- When reporting activity or inactivity, note time of day when available — it helps correlate with glucose patterns (if the patient tracks glucose) or with energy/sleep patterns otherwise"
        + _LANE_RULE
    ),
)

VITALS_SPEC = DomainSpec(
    domain="vitals",
    data_types=_domain_data_types("vitals", "profile"),
    system_prompt=(
        "You are a VITALS and body metrics specialist. Your domain: blood pressure, heart rate, "
        "weight, SpO2, profile, and body composition only. Focus on:\n"
        "- Blood pressure trends against standard reference ranges\n"
        "- Resting heart rate patterns and variability\n"
        "- Weight trends over time — progress toward weight loss goals\n"
        "- BMI trajectory and body composition: skeletal muscle mass, body fat %, visceral fat, "
        "segmental lean balance, phase angle — compare scans, note muscle vs fat shifts\n"
        "- SpO2 readings if available\n"
        "- Flag concerning trends: rising BP, rapid weight gain, muscle loss, abnormal HR"
        + _LANE_RULE
    ),
)

SLEEP_SPEC = DomainSpec(
    domain="sleep",
    data_types=_domain_data_types("sleep"),
    system_prompt=(
        "You are a SLEEP & WELLNESS specialist. Your domains: sleep data, self-reported sleep check-ins, mood entries, and symptom entries.\n"
        "Focus on:\n"
        "- Sleep duration trends (recommended 7-9 hours for metabolic health)\n"
        "- Self-reported sleep quality patterns from daily check-ins\n"
        "- Sleep consistency (regular vs irregular schedule)\n"
        "- Mood patterns: level trends, recurring tags (stressed, anxious, energetic)\n"
        "- Sleep-mood correlation: does poor sleep precede low mood?\n"
        "- Symptom tracking: severity trends, frequency of specific symptoms over time\n"
        "- Symptom-mood-sleep correlation: do symptoms worsen with poor sleep or low mood?\n"
        "- GLP-1 / medication side effect patterns: GI symptoms (nausea, constipation), fatigue\n"
        "- If the patient has glucose/CGM data: impact of sleep, mood, and symptoms on glucose control\n"
        "- Sleep apnea indicators when the data suggests them (snoring reports, low SpO2, fragmented sleep)\n"
        "- Flag concerning patterns: chronic short sleep, persistent low mood, deteriorating quality, escalating symptom severity\n"
        "- When reporting issues, note the date — it helps correlate across domains"
        + _LANE_RULE
    ),
)

DOCUMENTS_SPEC = DomainSpec(
    domain="documents",
    data_types=_domain_data_types("documents"),
    system_prompt=(
        "You are a MEDICAL DOCUMENTS specialist. Your domain: lab reports, prescriptions, "
        "clinical notes, and body composition reports. Focus on:\n"
        "- Lab results: HbA1c trends, lipid panel, kidney function (eGFR, creatinine)\n"
        "- Body composition: InBody reports, DEXA scans — weight, body fat %, skeletal muscle mass, visceral fat\n"
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

    # ── Public API (unchanged signatures) ─────────────────────────────

    async def investigate(
        self,
        *,
        messages: list[dict[str, Any]],
        patient_ids: list[str],
        max_rounds: int = 3,
        model_id: str,
        patient_names: dict[str, str] | None = None,
        trace_id: str | None = None,
    ) -> SpecialistFindings:
        """Run a domain-scoped investigation."""
        async for item in self._investigate_core(
            messages=messages,
            patient_ids=patient_ids,
            max_rounds=max_rounds,
            model_id=model_id,
            patient_names=patient_names,
            emit_events=False,
            trace_id=trace_id,
        ):
            if isinstance(item, SpecialistFindings):
                return item
        # Unreachable — _investigate_core always yields SpecialistFindings at the end.
        raise RuntimeError("_investigate_core did not produce SpecialistFindings")  # pragma: no cover

    async def investigate_stream(
        self,
        *,
        messages: list[dict[str, Any]],
        patient_ids: list[str],
        max_rounds: int = 3,
        model_id: str,
        patient_names: dict[str, str] | None = None,
        trace_id: str | None = None,
    ) -> AsyncIterator[str]:
        """Streaming version that yields SSE events during investigation."""
        async for item in self._investigate_core(
            messages=messages,
            patient_ids=patient_ids,
            max_rounds=max_rounds,
            model_id=model_id,
            patient_names=patient_names,
            emit_events=True,
            trace_id=trace_id,
        ):
            if isinstance(item, str):
                yield item

    # ── Core loop (shared implementation) ─────────────────────────────

    async def _investigate_core(
        self,
        *,
        messages: list[dict[str, Any]],
        patient_ids: list[str],
        max_rounds: int = 3,
        model_id: str,
        patient_names: dict[str, str] | None = None,
        emit_events: bool = False,
        trace_id: str | None = None,
    ) -> AsyncIterator[str | SpecialistFindings]:
        """Unified investigation loop that yields SSE strings and/or SpecialistFindings."""
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

        # Ensure at least 2 rounds when fallback lookup is possible so the LLM sees data
        if self._spec.data_types and max_rounds < 2:
            max_rounds = 2

        for round_num in range(1, max_rounds + 1):
            response = await self._gateway.complete_with_tools(
                messages=specialist_messages,
                tools=tool_schemas,
                task=ModelTask.CLASSIFICATION,
                model_id=model_id,
                timeout=settings.REASONING_TIMEOUT_SECONDS,
                trace_id=trace_id,
            )
            total_cost += safe_cost(response)

            if not response.has_tool_calls:
                if round_num == 1 and self._spec.data_types and not seen_calls:
                    fallback_result = await self._tools.execute(
                        "look_up",
                        {"data_types": self._spec.data_types, "limit": settings.LOOKUP_DEFAULT_LIMIT},
                        patient_ids,
                        patient_names=patient_names,
                    )
                    seen_calls.add("look_up:fallback")
                    total_tools += 1
                    if not is_no_data(fallback_result):
                        findings_parts.append(fallback_result)
                    specialist_messages.append({
                        "role": "system",
                        "content": f"Health data retrieved:\n\n{fallback_result}",
                    })
                    if emit_events:
                        yield sse_tool_call("look_up", {"data_types": self._spec.data_types, "limit": settings.LOOKUP_DEFAULT_LIMIT})
                        lines = fallback_result.strip().split("\n")
                        summary = lines[0][:settings.SUMMARY_TRUNCATION_CHARS] if lines else "No data"
                        yield sse_tool_result("look_up", summary)
                    continue

                if response.content:
                    findings_parts.append(response.content)
                if emit_events and response.content:
                    yield sse_reasoning(round_num, f"[{self._spec.domain}] {response.content}")
                break

            if emit_events and response.content:
                yield sse_reasoning(round_num, f"[{self._spec.domain}] {response.content}")

            # Execute tool round via shared helper
            tool_round = await self._tools.execute_tool_round(response, patient_ids, seen_calls, patient_names=patient_names)
            specialist_messages.append(tool_round.assistant_message)
            specialist_messages.extend(tool_round.tool_messages)
            total_tools += tool_round.executed_count

            # Collect findings from results (exclude [NO_DATA] sentinels)
            findings_parts.extend(r for r in tool_round.results if not is_no_data(r))

            # Emit tool events (streaming only)
            if emit_events:
                for tc in response.tool_calls:
                    call_key = f"{tc.function_name}:{json.dumps(tc.arguments, sort_keys=True)}"
                    # Emit only for calls that were actually executed (not dups)
                    # We check if it's in seen_calls after execute_tool_round added them
                    yield sse_tool_call(tc.function_name, tc.arguments)
                for result_text in tool_round.results:
                    lines = result_text.strip().split("\n")
                    summary = lines[0][:settings.SUMMARY_TRUNCATION_CHARS] if lines else "No data"
                    yield sse_tool_result(self._spec.domain, summary)

            # Early exit: if all results are "no data", stop investigating
            if tool_round.all_no_data:
                break

        yield SpecialistFindings(
            domain=self._spec.domain,
            findings="\n\n".join(findings_parts),
            tool_calls_used=total_tools,
            data_gathered=[f[:settings.SUMMARY_TRUNCATION_CHARS] for f in findings_parts],
            cost=total_cost,
        )
