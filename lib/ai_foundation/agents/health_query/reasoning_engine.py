"""
Reasoning Engine — agentic loop where the LLM investigates patient data.

The LLM acts like a personal doctor: sees data, forms hypotheses, fetches more
data, finds patterns, and builds a connected health story.

Architecture:
    Thinker (cheap, fast) → reasons about what to fetch, calls tools
    Responder (powerful)  → generates the final human-facing response

The thinker runs in a loop:
    1. See patient context + question
    2. Decide which tool(s) to call
    3. Get results, reason about what they mean
    4. Decide: need more data? → loop again. Have enough? → stop.
    5. Responder takes everything and writes a polished answer.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, AsyncIterator

from lib.ai_foundation.config import settings
from lib.ai_foundation.models.gateway import safe_cost
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.streaming.sse import (
    PipelineStage,
    SSEDonePayload,
    sse_plan,
    sse_reasoning,
    sse_reflection,
    sse_status,
    sse_bubble,
    sse_error,
    sse_token,
    sse_tool_call,
    sse_tool_result,
)

if TYPE_CHECKING:
    from lib.ai_foundation.agents.core.context_loader import AgentContext
    from lib.ai_foundation.agents.health_query.planner import InvestigationPlanner
    from lib.ai_foundation.agents.health_query.reflector import ReflectionEngine
    from lib.ai_foundation.agents.health_query.tools import ToolExecutor
    from lib.ai_foundation.models.gateway import ModelGateway

from lib.ai_foundation.agents.core.context_loader import build_context_messages
from lib.ai_foundation.agents.health_query.evidence import (
    EvidenceItem,
    build_summary,
    compute_coverage_confidence,
    detect_conflicts,
    extract_evidence_from_fallback,
    extract_evidence_from_tool_round,
    format_data_gaps,
    format_evidence_block,
)

logger = logging.getLogger(__name__)

from lib.ai_foundation.agents.core.bubbles import BubbleStreamFilter, extract_await, strip_bubbles
from lib.ai_foundation.agents.core.chart_processor import process_charts
from lib.ai_foundation.agents.core.context_pruner import ContextPruner


@contextmanager
def _track_perf(perf: dict[str, int], key: str):
    """Time a block and accumulate milliseconds into perf[key]."""
    start = time.perf_counter()
    yield
    perf[key] += int((time.perf_counter() - start) * 1000)


# ── Tier Configuration ─────────────────────────────────────────────────────


class ReasoningTier(str, Enum):
    """Configurable reasoning depth — affects tool call budget and model quality."""

    BASIC = "basic"
    STANDARD = "standard"
    ADVANCED = "advanced"
    UNLIMITED = "unlimited"


@dataclass(frozen=True)
class TierConfig:
    max_tool_calls: int
    thinker_model: str
    responder_model: str
    show_reasoning: bool


TIER_CONFIGS: dict[ReasoningTier, TierConfig] = {
    ReasoningTier.BASIC: TierConfig(
        max_tool_calls=2,
        thinker_model=settings.REASONING_THINKER_MODEL,
        responder_model=settings.REASONING_THINKER_MODEL,  # same cheap model for basic
        show_reasoning=False,
    ),
    ReasoningTier.STANDARD: TierConfig(
        max_tool_calls=5,
        thinker_model=settings.REASONING_THINKER_MODEL,
        responder_model=settings.REASONING_RESPONDER_MODEL,
        show_reasoning=True,
    ),
    ReasoningTier.ADVANCED: TierConfig(
        max_tool_calls=10,
        thinker_model=settings.REASONING_ADVANCED_THINKER_MODEL,
        responder_model=settings.REASONING_RESPONDER_MODEL,
        show_reasoning=True,
    ),
    ReasoningTier.UNLIMITED: TierConfig(
        max_tool_calls=20,
        thinker_model=settings.REASONING_ADVANCED_THINKER_MODEL,
        responder_model=settings.REASONING_RESPONDER_MODEL,
        show_reasoning=True,
    ),
}


# ── Result Models ──────────────────────────────────────────────────────────


@dataclass
class ReasoningStep:
    """One round of the reasoning loop."""

    round: int
    thought: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReasoningResult:
    """Complete output from the reasoning engine."""

    response: str
    steps: list[ReasoningStep] = field(default_factory=list)
    rounds_used: int = 0
    tools_called: int = 0
    total_cost: float = 0.0
    thinker_model: str = ""
    responder_model: str = ""
    tier: str = ""
    perf: dict[str, int] = field(default_factory=dict)
    coverage_confidence: float | None = None
    reflection_confidence: float | None = None
    data_gaps: list[str] | None = None
    data_conflicts: list[str] | None = None


# ── Engine ─────────────────────────────────────────────────────────────────


class ReasoningEngine:
    """Agentic reasoning loop — the LLM investigates like a doctor.

    Usage::

        engine = ReasoningEngine(gateway=gw, tool_executor=te)
        result = await engine.reason(
            user_message="Why am I having glucose spikes?",
            system_prompt="You are a health assistant...",
            context=agent_context,
            patient_ids=["p123"],
            tier=ReasoningTier.STANDARD,
        )
    """

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        tool_executor: ToolExecutor,
        planner: InvestigationPlanner | None = None,
        reflector: ReflectionEngine | None = None,
    ) -> None:
        self._gateway = gateway
        self._tools = tool_executor
        self._planner = planner
        self._reflector = reflector
        self._pruner = ContextPruner(gateway=gateway)

    # ── Context Window Management (delegated to ContextPruner) ────────

    def _get_input_budget(self, model: str) -> int:
        return self._pruner.get_input_budget(model)

    def _prune_if_needed(self, messages: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
        return self._pruner.prune_if_needed(messages, model)

    # ── Public API (unchanged signatures) ─────────────────────────────

    async def reason(
        self,
        *,
        user_message: str,
        system_prompt: str,
        reasoning_prompt: str,
        response_prompt: str,
        context: AgentContext,
        patient_ids: list[str],
        tier: ReasoningTier = ReasoningTier.STANDARD,
        intent_data_types: list[str] | None = None,
        patient_names: dict[str, str] | None = None,
        user_role: str = "patient",
    ) -> ReasoningResult:
        """Run the full reasoning loop and return the result."""
        async for item in self._reason_core(
            user_message=user_message,
            system_prompt=system_prompt,
            reasoning_prompt=reasoning_prompt,
            response_prompt=response_prompt,
            context=context,
            patient_ids=patient_ids,
            tier=tier,
            intent_data_types=intent_data_types,
            patient_names=patient_names,
            user_role=user_role,
            emit_events=False,
        ):
            if isinstance(item, ReasoningResult):
                return item
        # Unreachable — _reason_core always yields a ReasoningResult at the end.
        raise RuntimeError("_reason_core did not produce a ReasoningResult")  # pragma: no cover

    async def reason_stream(
        self,
        *,
        user_message: str,
        system_prompt: str,
        reasoning_prompt: str,
        response_prompt: str,
        context: AgentContext,
        patient_ids: list[str],
        tier: ReasoningTier = ReasoningTier.STANDARD,
        intent_data_types: list[str] | None = None,
        patient_names: dict[str, str] | None = None,
        user_role: str = "patient",
        delta_sink: list[str] | None = None,
    ) -> AsyncIterator[str | SSEDonePayload]:
        """Run the reasoning loop, yielding SSE events as the doctor thinks.

        Yields formatted SSE strings, then a terminal SSEDonePayload carrying
        the structured result (full response, cost, evidence metrics).
        """
        async for item in self._reason_core(
            user_message=user_message,
            system_prompt=system_prompt,
            reasoning_prompt=reasoning_prompt,
            response_prompt=response_prompt,
            context=context,
            patient_ids=patient_ids,
            tier=tier,
            intent_data_types=intent_data_types,
            patient_names=patient_names,
            user_role=user_role,
            emit_events=True,
            delta_sink=delta_sink,
        ):
            if isinstance(item, (str, SSEDonePayload)):
                yield item

    # ── Core loop (shared implementation) ─────────────────────────────

    async def _reason_core(
        self,
        *,
        user_message: str,
        system_prompt: str,
        reasoning_prompt: str,
        response_prompt: str,
        context: AgentContext,
        patient_ids: list[str],
        tier: ReasoningTier = ReasoningTier.STANDARD,
        intent_data_types: list[str] | None = None,
        patient_names: dict[str, str] | None = None,
        user_role: str = "patient",
        emit_events: bool = False,
        delta_sink: list[str] | None = None,
    ) -> AsyncIterator[str | ReasoningResult]:
        """Unified reasoning loop that yields SSE strings and/or a ReasoningResult."""
        tier_cfg = TIER_CONFIGS[tier]
        tool_schemas = self._tools.get_openai_schemas()
        messages = build_context_messages(
            user_message=user_message,
            system_prompt=system_prompt,
            reasoning_prompt=reasoning_prompt,
            context=context,
        )

        steps: list[ReasoningStep] = []
        total_cost = 0.0
        total_tools = 0
        rounds_used = 0
        seen_calls: set[str] = set()  # deduplication
        budget_remaining = tier_cfg.max_tool_calls
        evidence_ledger: list[EvidenceItem] = []  # pruning-safe evidence trail

        pipeline_start = time.perf_counter()
        perf: dict[str, int] = {
            "planning_ms": 0,
            "thinker_llm_ms": 0,
            "tool_exec_ms": 0,
            "reflection_ms": 0,
            "responder_ms": 0,
            "total_ms": 0,
        }

        if emit_events:
            yield sse_status(PipelineStage.ANALYZING, "Investigating health data...")

        # ── Planning phase (STANDARD+ tiers) ──
        if self._planner and settings.PLANNING_ENABLED and tier_cfg.max_tool_calls > 2:
            with _track_perf(perf, "planning_ms"):
                _meta = getattr(context, "metadata", None) or {}
                is_voice = _meta.get("output_mode") == "voice"
                plan = await self._execute_plan(
                    messages=messages,
                    tool_schemas=tool_schemas,
                    tier_cfg=tier_cfg,
                    patient_ids=patient_ids,
                    seen_calls=seen_calls,
                    patient_names=patient_names,
                    is_voice=is_voice,
                )
            total_cost += plan["cost"]
            total_tools += plan["tools_called"]
            budget_remaining -= plan["tools_called"]
            budget_remaining = max(1, budget_remaining)  # ensure at least 1 investigation round
            if plan["steps"]:
                steps.extend(plan["steps"])

            # Emit plan event (streaming only)
            if emit_events and plan.get("plan_obj"):
                yield sse_plan(
                    plan["plan_obj"].strategy,
                    len(plan["plan_obj"].steps),
                    plan["plan_obj"].domains_involved,
                )

        for round_num in range(1, budget_remaining + 1):
            # Prune before thinker call
            messages = self._prune_if_needed(messages, tier_cfg.thinker_model)

            with _track_perf(perf, "thinker_llm_ms"):
                tokens = self._gateway.count_tokens(messages, tier_cfg.thinker_model)
                budget = self._get_input_budget(tier_cfg.thinker_model)
                logger.info("LLM call [thinker] round=%d: %d tokens (budget=%d, %.0f%%)",
                            round_num, tokens, budget, tokens / max(budget, 1) * 100)

                response = await self._gateway.complete_with_tools(
                    messages=messages,
                    tools=tool_schemas,
                    task=ModelTask.CLASSIFICATION,
                    model_id=tier_cfg.thinker_model,
                    timeout=settings.REASONING_TIMEOUT_SECONDS,
                )
            total_cost += safe_cost(response)

            if not response.has_tool_calls:
                # Round 1 with no tool calls = lazy LLM. Force a lookup.
                if round_num == 1 and intent_data_types and not seen_calls:
                    if emit_events and tier_cfg.show_reasoning:
                        yield sse_tool_call("look_up", {"data_types": intent_data_types})
                    with _track_perf(perf, "tool_exec_ms"):
                        fallback_result = await self._tools.execute(
                            "look_up",
                            {"data_types": intent_data_types, "limit": settings.LOOKUP_DEFAULT_LIMIT},
                            patient_ids,
                            patient_names=patient_names,
                        )
                    seen_calls.add("look_up:fallback")
                    total_tools += 1
                    evidence_ledger.append(extract_evidence_from_fallback(
                        "look_up",
                        {"data_types": intent_data_types, "limit": settings.LOOKUP_DEFAULT_LIMIT},
                        fallback_result,
                    ))
                    steps.append(ReasoningStep(
                        round=round_num,
                        thought="Fetching data based on query intent.",
                        tool_calls=[{"tool": "look_up", "args": {"data_types": intent_data_types}}],
                        tool_results=[{"tool": "look_up", "result": fallback_result[:settings.STEP_LOG_TRUNCATION_CHARS]}],
                    ))
                    if emit_events and tier_cfg.show_reasoning:
                        summary = self._summarize_result("look_up", fallback_result)
                        yield sse_tool_result("look_up", summary)
                    messages.append({
                        "role": "system",
                        "content": f"Health data retrieved:\n\n{fallback_result}",
                        "_meta": {"type": "tool_result", "round": round_num, "tool": "look_up"},
                    })
                    continue  # Let the thinker see the data and try again

                if response.content:
                    steps.append(ReasoningStep(
                        round=round_num, thought=response.content,
                    ))
                if emit_events and tier_cfg.show_reasoning and response.content:
                    yield sse_reasoning(round_num, response.content)
                rounds_used = round_num
                break

            # Emit reasoning thought
            if emit_events and tier_cfg.show_reasoning and response.content:
                yield sse_reasoning(round_num, response.content)

            step = ReasoningStep(round=round_num, thought=response.content)

            # Execute tool round via shared helper
            with _track_perf(perf, "tool_exec_ms"):
                tool_round = await self._tools.execute_tool_round(response, patient_ids, seen_calls, patient_names=patient_names)

            # Tag assistant message with round metadata
            assistant_msg = {**tool_round.assistant_message, "_meta": {"type": "assistant_tool_calls", "round": round_num}}
            messages.append(assistant_msg)

            # Tag tool result messages with round + tool metadata
            tc_by_id = {tc.id: tc for tc in response.tool_calls}
            for msg in tool_round.tool_messages:
                tc_id = msg.get("tool_call_id", "")
                tc = tc_by_id.get(tc_id)
                tool_name = tc.function_name if tc else "unknown"
                tagged = {**msg, "_meta": {"type": "tool_result", "round": round_num, "tool": tool_name}}
                messages.append(tagged)

            total_tools += tool_round.executed_count
            evidence_ledger.extend(extract_evidence_from_tool_round(response, tool_round.tool_messages))

            # Stop if cumulative tool calls have reached the budget
            if total_tools >= tier_cfg.max_tool_calls:
                rounds_used = round_num
                break

            # Emit tool events (streaming only)
            if emit_events and tier_cfg.show_reasoning:
                for tc in response.tool_calls:
                    yield sse_tool_call(tc.function_name, tc.arguments)
                for msg in tool_round.tool_messages:
                    tc_id = msg.get("tool_call_id", "")
                    tc = tc_by_id.get(tc_id)
                    if not tc:
                        continue
                    summary = self._summarize_result(tc.function_name, msg.get("content", ""))
                    yield sse_tool_result(tc.function_name, summary)

            # Build step log for non-streaming tracking
            for msg in tool_round.tool_messages:
                tc_id = msg.get("tool_call_id", "")
                content = msg.get("content", "")
                tc = tc_by_id.get(tc_id)
                if not tc:
                    continue
                step.tool_calls.append({"tool": tc.function_name, "args": tc.arguments})
                step.tool_results.append({"tool": tc.function_name, "result": content[:settings.STEP_LOG_TRUNCATION_CHARS]})

            steps.append(step)
            rounds_used = round_num

            # Early exit: if all results indicate no data, stop investigating
            if tool_round.all_no_data:
                break
        else:
            # Max rounds reached — add hint to wrap up
            messages.append({
                "role": "system",
                "content": (
                    "You have reached the maximum number of investigation rounds. "
                    "Generate your best response with the data you have gathered so far."
                ),
                "_meta": {"type": "system_hint"},
            })

        # ── Reflection (ADVANCED+ tiers) ──
        reflection_result = None
        if self._reflector and settings.REFLECTION_ENABLED and tier_cfg.max_tool_calls >= 10:
            with _track_perf(perf, "reflection_ms"):
                reflection = await self._reflect_and_followup(
                    messages=messages,
                    user_message=user_message,
                    tool_schemas=tool_schemas,
                    tier_cfg=tier_cfg,
                    patient_ids=patient_ids,
                    seen_calls=seen_calls,
                    steps=steps,
                    total_cost=total_cost,
                    total_tools=total_tools,
                    patient_names=patient_names,
                    evidence_ledger=evidence_ledger,
                )
            total_cost = reflection["total_cost"]
            total_tools = reflection["total_tools"]

            if emit_events and reflection.get("result"):
                r = reflection["result"]
                yield sse_reflection(r.confidence, r.gaps, r.is_complete)

            reflection_result = reflection.get("result")

        # ── Final response ──
        if emit_events:
            # Stream final response
            yield sse_status(
                PipelineStage.GENERATING_RESPONSE,
                "Building personalized insights...",
            )

            responder_messages = self._build_responder_messages(
                messages, response_prompt,
                user_role=user_role, evidence_ledger=evidence_ledger,
            )
            responder_messages = self._prune_if_needed(responder_messages, tier_cfg.responder_model)

            tokens = self._gateway.count_tokens(responder_messages, tier_cfg.responder_model)
            resp_budget = self._get_input_budget(tier_cfg.responder_model)
            logger.info("LLM call [responder-stream]: %d tokens (budget=%d, %.0f%%)",
                        tokens, resp_budget, tokens / max(resp_budget, 1) * 100)

            full_response_parts: list[str] = []
            responder_start = time.perf_counter()
            # Visible stream never carries the bubble sentinel; the raw text
            # (with sentinels) is kept for done-payload splitting.
            bubble_filter = BubbleStreamFilter()

            try:
                async for chunk in self._gateway.stream(
                    messages=responder_messages,
                    task=ModelTask.RESPONSE_GENERATION,
                    model_id=tier_cfg.responder_model,
                    timeout=settings.RESPONDER_TIMEOUT_SECONDS,
                ):
                    if chunk.delta:
                        full_response_parts.append(chunk.delta)
                        if delta_sink is not None:
                            delta_sink.append(chunk.delta)
                        for kind, piece in bubble_filter.feed_events(chunk.delta):
                            if kind == "bubble":
                                yield sse_bubble()
                            elif piece:
                                yield sse_token(piece)
                    if chunk.finished and chunk.usage:
                        total_cost += safe_cost(chunk)
            except Exception as exc:
                logger.error(
                    "Responder stream failed after %d chunks: %s",
                    len(full_response_parts), exc,
                )
                yield sse_error(
                    message="The response was interrupted. Please try again.",
                    code="stream_error",
                    fallback_text=strip_bubbles(extract_await("".join(full_response_parts))[0]) or None,
                )
                return

            tail = bubble_filter.flush()
            if tail:
                yield sse_token(tail)
            perf["responder_ms"] += int((time.perf_counter() - responder_start) * 1000)
        else:
            # Non-streaming: single responder call
            with _track_perf(perf, "responder_ms"):
                final_response = await self._generate_final_response(
                    messages=messages,
                    response_prompt=response_prompt,
                    model_id=tier_cfg.responder_model,
                    user_role=user_role,
                    evidence_ledger=evidence_ledger,
                )
            total_cost += safe_cost(final_response)

        # ── Finalize perf + evidence (shared) ──
        perf["total_ms"] = int((time.perf_counter() - pipeline_start) * 1000)
        logger.debug(
            "Reasoning perf(ms): planning=%d thinker=%d tools=%d reflection=%d responder=%d total=%d",
            perf["planning_ms"],
            perf["thinker_llm_ms"],
            perf["tool_exec_ms"],
            perf["reflection_ms"],
            perf["responder_ms"],
            perf["total_ms"],
        )

        evidence = self._compute_evidence_result(
            evidence_ledger, reflection_result, tier, rounds_used, total_tools, steps, perf,
        )

        if emit_events:
            # Yield the structured payload — the agent builds the final done
            # event itself (no serialize → string-parse → re-serialize round-trip).
            yield SSEDonePayload(
                cost_usd=total_cost,
                data={
                    **evidence,
                    "tier": tier.value,
                    "full_response": process_charts("".join(full_response_parts)),
                },
            )
        else:
            yield ReasoningResult(
                response=process_charts(final_response.content or ""),
                thinker_model=tier_cfg.thinker_model,
                responder_model=tier_cfg.responder_model,
                total_cost=total_cost,
                tier=tier.value,
                **evidence,
            )

    # ── Evidence computation (shared by streaming + non-streaming) ─────

    @staticmethod
    def _compute_evidence_result(
        evidence_ledger: list[EvidenceItem],
        reflection_result: Any,
        tier: ReasoningTier,
        rounds_used: int,
        total_tools: int,
        steps: list[ReasoningStep],
        perf: dict[str, int],
    ) -> dict[str, Any]:
        """Build the evidence metrics dict used by both streaming and non-streaming paths.

        Returns a dict with keys matching ReasoningResult fields:
        rounds_used, tools_called, steps, perf, coverage_confidence,
        reflection_confidence, data_gaps, data_conflicts.
        """
        summary = build_summary(evidence_ledger)
        return {
            "rounds_used": rounds_used,
            "tools_called": total_tools,
            "steps": steps,
            "perf": perf,
            "coverage_confidence": compute_coverage_confidence(summary),
            "reflection_confidence": reflection_result.confidence if reflection_result else None,
            "data_gaps": format_data_gaps(summary),
            "data_conflicts": detect_conflicts(evidence_ledger) or None,
        }

    # ── Planning ───────────────────────────────────────────────────────

    async def _execute_plan(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        tier_cfg: TierConfig,
        patient_ids: list[str],
        seen_calls: set[str],
        patient_names: dict[str, str] | None = None,
        is_voice: bool = False,
    ) -> dict[str, Any]:
        """Generate an investigation plan and add it as context for the thinker.

        The plan is GUIDANCE, not execution. The thinker makes the actual
        tool calls (which are enum-constrained via OpenAI function calling).
        This prevents the planner from passing invalid data_types like "meals"
        directly to Qdrant.

        Returns dict with: cost, tools_called, steps, plan_obj.
        """
        try:
            planning_prompt = (
                "Plan the investigation. Output a structured InvestigationPlan. "
                "Write the strategy field as if you are a doctor explaining your plan "
                "to the patient out loud — first person, conversational, no jargon."
            ) if is_voice else "Plan the investigation. Output a structured InvestigationPlan."

            plan, plan_cost = await self._planner.plan(
                messages=messages,
                tool_schemas=tool_schemas,
                planning_prompt=planning_prompt,
                model_id=tier_cfg.thinker_model,
            )

            # Add plan as context — the thinker reads this and executes with proper tool calls
            step_lines = []
            for s in plan.steps:
                step_lines.append(f"  Phase {s.phase}: {s.tool_name}({json.dumps(s.arguments)}) — {s.reason}")

            messages.append({
                "role": "system",
                "content": (
                    f"INVESTIGATION PLAN: {plan.strategy}\n"
                    f"Planned steps:\n" + "\n".join(step_lines) + "\n\n"
                    f"Execute these steps using your tools. Start with Phase 1."
                ),
                "_meta": {"type": "plan"},
            })

            return {
                "cost": plan_cost,
                "tools_called": 0,
                "steps": [],
                "plan_obj": plan,
            }

        except Exception as exc:
            logger.warning("Planning failed (%s): %s", type(exc).__name__, exc)
            return {"cost": 0, "tools_called": 0, "steps": [], "plan_obj": None}

    # ── Reflection ─────────────────────────────────────────────────────

    async def _reflect_and_followup(
        self,
        *,
        messages: list[dict[str, Any]],
        user_message: str,
        tool_schemas: list[dict[str, Any]],
        tier_cfg: TierConfig,
        patient_ids: list[str],
        seen_calls: set[str],
        steps: list[ReasoningStep],
        total_cost: float,
        total_tools: int,
        patient_names: dict[str, str] | None = None,
        evidence_ledger: list | None = None,
    ) -> dict[str, Any]:
        """Run reflection and optional gap-filling follow-up.

        Returns dict with: total_cost, total_tools, result (ReflectionResult or None).
        """
        try:
            reflection_prompt = (
                "Review this health data investigation. "
                "Assess completeness, identify gaps, and flag safety concerns."
            )

            result = await self._reflector.reflect(
                messages=messages,
                user_question=user_message,
                reflection_prompt=reflection_prompt,
                model_id=tier_cfg.thinker_model,
            )

            # If gaps found, do targeted follow-up (budget permitting)
            max_reflection_rounds = (
                settings.REFLECTION_MAX_ROUNDS
                if tier_cfg.max_tool_calls >= 20
                else 1
            )

            for reflection_round in range(max_reflection_rounds):
                if result.is_complete or not result.gaps:
                    break

                # Add gaps as investigation guidance
                gap_text = "\n".join(f"- {g}" for g in result.gaps)
                messages.append({
                    "role": "system",
                    "content": (
                        f"REFLECTION identified gaps in the investigation:\n{gap_text}\n\n"
                        f"Please investigate these specific areas to complete the analysis."
                    ),
                    "_meta": {"type": "reflection"},
                })

                # One more reasoning round to fill gaps
                messages = self._prune_if_needed(messages, tier_cfg.thinker_model)
                response = await self._gateway.complete_with_tools(
                    messages=messages,
                    tools=tool_schemas,
                    task=ModelTask.CLASSIFICATION,
                    model_id=tier_cfg.thinker_model,
                    timeout=settings.REASONING_TIMEOUT_SECONDS,
                )
                total_cost += safe_cost(response)

                if response.has_tool_calls:
                    tool_round = await self._tools.execute_tool_round(response, patient_ids, seen_calls, patient_names=patient_names)
                    # Continue the main loop's round numbering — round 0 would
                    # fall through the pruner (neither summarized nor protected
                    # as recent).
                    followup_round = 1 + max(
                        (m.get("_meta", {}).get("round", 0) for m in messages),
                        default=0,
                    )
                    messages.append({**tool_round.assistant_message, "_meta": {"type": "assistant_tool_calls", "round": followup_round}})
                    tc_by_id = {tc.id: tc for tc in response.tool_calls}
                    for msg in tool_round.tool_messages:
                        tc = tc_by_id.get(msg.get("tool_call_id", ""))
                        tool_name = tc.function_name if tc else "unknown"
                        messages.append({**msg, "_meta": {"type": "tool_result", "round": followup_round, "tool": tool_name}})
                    total_tools += tool_round.executed_count
                    if evidence_ledger is not None:
                        evidence_ledger.extend(extract_evidence_from_tool_round(response, tool_round.tool_messages))

                # Re-reflect if we have budget for another round
                if reflection_round < max_reflection_rounds - 1:
                    result = await self._reflector.reflect(
                        messages=messages,
                        user_question=user_message,
                        reflection_prompt=reflection_prompt,
                        model_id=tier_cfg.thinker_model,
                    )

            # Add safety concerns to context if found
            if result.safety_concerns:
                concerns = "\n".join(f"- {c}" for c in result.safety_concerns)
                messages.append({
                    "role": "system",
                    "content": (
                        f"SAFETY NOTE — mention these concerns in the response "
                        f"(suggest discussing with care team):\n{concerns}"
                    ),
                    "_meta": {"type": "reflection"},
                })

            return {
                "total_cost": total_cost,
                "total_tools": total_tools,
                "result": result,
            }

        except Exception as exc:
            logger.warning("Reflection failed (%s): %s", type(exc).__name__, exc)
            return {
                "total_cost": total_cost,
                "total_tools": total_tools,
                "result": None,
            }

    # ── Message Builders ───────────────────────────────────────────────

    def _build_responder_messages(
        self,
        reasoning_messages: list[dict[str, Any]],
        response_prompt: str,
        *,
        user_role: str = "patient",
        evidence_ledger: list | None = None,
    ) -> list[dict[str, Any]]:
        """Build messages for the responder model.

        Takes the full reasoning conversation and restructures it for the
        responder: system prompt + gathered data summary + evidence + user question.
        """
        # Extract system messages (with _meta), user message, and all tool results
        system_msgs: list[dict[str, Any]] = []
        history_msgs: list[dict[str, Any]] = []
        user_msg = ""
        gathered_data: list[str] = []

        for msg in reasoning_messages:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""
            meta = msg.get("_meta", {})

            if role == "system":
                _exclude = {"instruction", "plan", "reflection", "system_hint", "tool_summary", "tool_result", "assistant_tool_calls"}
                msg_type = meta.get("type", "")
                if msg_type == "tool_result":
                    gathered_data.append(content)
                elif msg_type not in _exclude:
                    system_msgs.append({"role": "system", "content": content, "_meta": meta} if meta else {"role": "system", "content": content})
            elif role == "user" and meta.get("type") == "history":
                history_msgs.append({"role": "user", "content": content, "_meta": meta})
            elif role == "assistant" and meta.get("type") == "history":
                history_msgs.append({"role": "assistant", "content": content, "_meta": meta})
            elif role == "user":
                user_msg = content
            elif role == "tool":
                gathered_data.append(content)
            elif role == "assistant" and content and not msg.get("tool_calls"):
                gathered_data.append(f"Analysis notes: {content}")

        # Build responder messages — propagate _meta for pruning
        messages: list[dict[str, Any]] = []

        # Keep original system prompts (patient context, names, facts)
        messages.extend(system_msgs)

        # Replace reasoning prompt with response prompt
        messages.append({"role": "system", "content": response_prompt, "_meta": {"type": "instruction"}})

        # Add gathered data as context
        if gathered_data:
            data_text = "\n\n---\n\n".join(gathered_data)
            if len(data_text) > settings.MAX_ANALYSIS_CHARS:
                data_text = data_text[:settings.MAX_ANALYSIS_CHARS] + "\n... (truncated)"
            messages.append({
                "role": "system",
                "content": f"HEALTH DATA GATHERED BY INVESTIGATION:\n\n{data_text}",
                "_meta": {"type": "gathered_data"},
            })

        # Inject evidence summary (pruning-safe — built from ledger, not messages)
        if evidence_ledger is not None:
            evidence_text = format_evidence_block(evidence_ledger, user_role)
            if evidence_text:
                messages.append({
                    "role": "system",
                    "content": f"INVESTIGATION EVIDENCE:\n{evidence_text}",
                    "_meta": {"type": "evidence_summary"},
                })

        messages.extend(history_msgs)
        messages.append({"role": "user", "content": user_msg, "_meta": {"type": "user_question"}})
        return messages

    async def _generate_final_response(
        self,
        *,
        messages: list[dict[str, Any]],
        response_prompt: str,
        model_id: str,
        user_role: str = "patient",
        evidence_ledger: list | None = None,
    ) -> Any:
        """Generate the final polished response from the responder model."""
        responder_messages = self._build_responder_messages(
            messages, response_prompt,
            user_role=user_role, evidence_ledger=evidence_ledger,
        )
        responder_messages = self._prune_if_needed(responder_messages, model_id)

        tokens = self._gateway.count_tokens(responder_messages, model_id)
        budget = self._get_input_budget(model_id)
        logger.info("LLM call [responder]: %d tokens (budget=%d, %.0f%%)",
                    tokens, budget, tokens / max(budget, 1) * 100)

        resp = await self._gateway.complete(
            messages=responder_messages,
            task=ModelTask.RESPONSE_GENERATION,
            model_id=model_id,
            # Long final answers exceed the model spec's default timeout;
            # explicit model_id also disables fallback, so a timeout here
            # would fail the whole query.
            timeout=settings.RESPONDER_TIMEOUT_SECONDS,
        )
        # Grounding gate: a health reply must not fabricate patient data, confirm
        # a false patient claim, or disavow real data. Verify against the same
        # evidence it was built from and correct once on a violation. Runs
        # even with an empty ledger: no-tool turns are exactly where the
        # responder spontaneously retracts its own prior-turn data, and the
        # verifier sees history/context as grounded sources.
        if (
            settings.GROUNDING_VERIFY_ENABLED and evidence_ledger is not None
            and (getattr(resp, "content", "") or "").strip()
        ):
            resp = await self._verify_and_correct(
                resp, responder_messages, evidence_ledger, user_role, model_id,
            )
        return resp

    async def _verify_and_correct(
        self, resp: Any, responder_messages: list[dict[str, Any]],
        evidence_ledger: list, user_role: str, model_id: str,
    ) -> Any:
        """Verify the draft against evidence; regenerate once with a targeted
        correction if it fabricates / confirms-a-false-claim / disavows real
        data. Any failure in the gate leaves the original response untouched —
        the gate can only improve the answer, never block it."""
        from lib.ai_foundation.agents.health_query.evidence import format_evidence_block
        from lib.ai_foundation.agents.health_query.grounding import (
            build_correction,
            verify_grounding,
        )
        try:
            evidence_text = format_evidence_block(evidence_ledger, user_role)
            # The responder legitimately grounds on more than this turn's tool
            # evidence: pre-loaded patient context (care intents, meds, memory
            # facts) and its OWN earlier turns. Verifying against tool evidence
            # alone forces false retractions of prior-turn data.
            context_parts = [
                m["content"] for m in responder_messages
                if m.get("_meta", {}).get("type") in ("context", "gathered_data")
            ]
            history_parts = [
                f"[{m['role']}] {m['content']}" for m in responder_messages
                if m.get("_meta", {}).get("type") == "history"
            ]
            if context_parts:
                evidence_text += (
                    "\n\n## PRE-LOADED PATIENT CONTEXT (grounded sources)\n"
                    + "\n\n".join(context_parts)
                )
            if history_parts:
                evidence_text += (
                    "\n\n## EARLIER CONVERSATION (assistant statements here were "
                    "grounded when made — retracting them is a violation)\n"
                    + "\n".join(history_parts)
                )
            verdict = await verify_grounding(
                self._gateway, response=resp.content, evidence_text=evidence_text,
            )
            if verdict.grounded:
                return resp
            logger.info(
                "Grounding gate: correcting (ungrounded=%d, wrongly_denied=%d)",
                len(verdict.ungrounded_claims), len(verdict.wrongly_denied),
            )
            corrected = await self._gateway.complete(
                messages=responder_messages
                + [{"role": "system", "content": build_correction(verdict)}],
                task=ModelTask.RESPONSE_GENERATION,
                model_id=model_id,
                timeout=settings.RESPONDER_TIMEOUT_SECONDS,
            )
            return corrected if (corrected.content or "").strip() else resp
        except Exception as exc:
            logger.warning("Grounding gate failed, using original response: %s", exc)
            return resp

    @staticmethod
    def _summarize_result(tool_name: str, result: str) -> str:
        """Create a brief summary of a tool result for SSE display."""
        lines = result.strip().split("\n")
        first_line = lines[0] if lines else "No data"
        entry_count = sum(1 for line in lines if line.strip().startswith("-"))

        if entry_count > 0:
            return f"{first_line} ({entry_count} entries)"
        if len(result) > 200:
            return result[:settings.SUMMARY_TRUNCATION_CHARS] + "..."
        return result
