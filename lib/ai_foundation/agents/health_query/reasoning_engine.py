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
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, AsyncIterator

from lib.ai_foundation.config import settings
from lib.ai_foundation.models.gateway import LLMToolResponse, LLMUsage, ToolCall
from lib.ai_foundation.models.pricing import CostBreakdown
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.streaming.sse import (
    PipelineStage,
    SSEDonePayload,
    sse_done,
    sse_error,
    sse_plan,
    sse_reasoning,
    sse_reflection,
    sse_status,
    sse_token,
    sse_tool_call,
    sse_tool_result,
)

if TYPE_CHECKING:
    from lib.ai_foundation.agents.health_query.context_loader import AgentContext
    from lib.ai_foundation.agents.health_query.planner import InvestigationPlanner
    from lib.ai_foundation.agents.health_query.reflector import ReflectionEngine
    from lib.ai_foundation.agents.health_query.tools import ToolExecutor
    from lib.ai_foundation.models.gateway import ModelGateway

from lib.ai_foundation.agents.health_query.context_loader import build_context_messages

logger = logging.getLogger(__name__)


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
        thinker_model="gpt-4.1",
        responder_model=settings.REASONING_RESPONDER_MODEL,
        show_reasoning=True,
    ),
    ReasoningTier.UNLIMITED: TierConfig(
        max_tool_calls=20,
        thinker_model="gpt-4.1",
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
    ) -> AsyncIterator[str]:
        """Run the reasoning loop, yielding SSE events as the doctor thinks."""
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
            emit_events=True,
        ):
            if isinstance(item, str):
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
        emit_events: bool = False,
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
            planning_start = time.perf_counter()
            plan = await self._execute_plan(
                messages=messages,
                tool_schemas=tool_schemas,
                tier_cfg=tier_cfg,
                patient_ids=patient_ids,
                seen_calls=seen_calls,
                patient_names=patient_names,
            )
            perf["planning_ms"] += int((time.perf_counter() - planning_start) * 1000)
            total_cost += plan["cost"]
            total_tools += plan["tools_called"]
            budget_remaining -= plan["tools_called"]
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
            thinker_start = time.perf_counter()
            response = await self._gateway.complete_with_tools(
                messages=messages,
                tools=tool_schemas,
                task=ModelTask.CLASSIFICATION,
                model_id=tier_cfg.thinker_model,
                timeout=settings.REASONING_TIMEOUT_SECONDS,
            )
            perf["thinker_llm_ms"] += int((time.perf_counter() - thinker_start) * 1000)
            total_cost += response.usage.cost.total_cost if response.usage.cost else 0

            if not response.has_tool_calls:
                # Round 1 with no tool calls = lazy LLM. Force a lookup.
                if round_num == 1 and intent_data_types and not seen_calls:
                    if emit_events and tier_cfg.show_reasoning:
                        yield sse_tool_call("look_up", {"data_types": intent_data_types})
                    tool_start = time.perf_counter()
                    fallback_result = await self._tools.execute(
                        "look_up",
                        {"data_types": intent_data_types, "limit": 15},
                        patient_ids,
                        patient_names=patient_names,
                    )
                    perf["tool_exec_ms"] += int((time.perf_counter() - tool_start) * 1000)
                    seen_calls.add("look_up:fallback")
                    total_tools += 1
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
            tool_start = time.perf_counter()
            tool_round = await self._tools.execute_tool_round(response, patient_ids, seen_calls, patient_names=patient_names)
            perf["tool_exec_ms"] += int((time.perf_counter() - tool_start) * 1000)
            messages.append(tool_round.assistant_message)
            messages.extend(tool_round.tool_messages)
            total_tools += tool_round.executed_count

            # Emit tool events (streaming only)
            if emit_events and tier_cfg.show_reasoning:
                tc_by_id = {tc.id: tc for tc in response.tool_calls}
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
            tc_by_id = {tc.id: tc for tc in response.tool_calls}
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
            })

        # ── Reflection (ADVANCED+ tiers) ──
        if self._reflector and settings.REFLECTION_ENABLED and tier_cfg.max_tool_calls >= 10:
            reflection_start = time.perf_counter()
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
            )
            perf["reflection_ms"] += int((time.perf_counter() - reflection_start) * 1000)
            total_cost = reflection["total_cost"]
            total_tools = reflection["total_tools"]

            if emit_events and reflection.get("result"):
                r = reflection["result"]
                yield sse_reflection(r.confidence, r.gaps, r.is_complete)

        # ── Final response ──
        if emit_events:
            # Stream final response
            yield sse_status(
                PipelineStage.GENERATING_RESPONSE,
                "Building personalized insights...",
            )

            responder_messages = self._build_responder_messages(messages, response_prompt)
            full_response_parts: list[str] = []
            responder_start = time.perf_counter()

            async for chunk in self._gateway.stream(
                messages=responder_messages,
                task=ModelTask.RESPONSE_GENERATION,
                model_id=tier_cfg.responder_model,
            ):
                if chunk.delta:
                    full_response_parts.append(chunk.delta)
                    yield sse_token(chunk.delta)
                if chunk.finished and chunk.usage:
                    total_cost += chunk.usage.cost.total_cost if chunk.usage.cost else 0

            perf["responder_ms"] += int((time.perf_counter() - responder_start) * 1000)
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

            yield sse_done(SSEDonePayload(
                cost_usd=total_cost,
                data={
                    "rounds_used": rounds_used,
                    "tools_called": total_tools,
                    "tier": tier.value,
                    "full_response": "".join(full_response_parts),
                    "perf": perf,
                },
            ))
        else:
            # Non-streaming: single responder call
            responder_start = time.perf_counter()
            final_response = await self._generate_final_response(
                messages=messages,
                response_prompt=response_prompt,
                model_id=tier_cfg.responder_model,
            )
            perf["responder_ms"] += int((time.perf_counter() - responder_start) * 1000)
            perf["total_ms"] = int((time.perf_counter() - pipeline_start) * 1000)
            total_cost += final_response.usage.cost.total_cost if final_response.usage.cost else 0
            logger.debug(
                "Reasoning perf(ms): planning=%d thinker=%d tools=%d reflection=%d responder=%d total=%d",
                perf["planning_ms"],
                perf["thinker_llm_ms"],
                perf["tool_exec_ms"],
                perf["reflection_ms"],
                perf["responder_ms"],
                perf["total_ms"],
            )

            yield ReasoningResult(
                response=final_response.content or "",
                steps=steps,
                rounds_used=rounds_used,
                tools_called=total_tools,
                total_cost=total_cost,
                thinker_model=tier_cfg.thinker_model,
                responder_model=tier_cfg.responder_model,
                tier=tier.value,
                perf=perf,
            )

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
    ) -> dict[str, Any]:
        """Generate an investigation plan and add it as context for the thinker.

        The plan is GUIDANCE, not execution. The thinker makes the actual
        tool calls (which are enum-constrained via OpenAI function calling).
        This prevents the planner from passing invalid data_types like "meals"
        directly to Qdrant.

        Returns dict with: cost, tools_called, steps, plan_obj.
        """
        try:
            plan = await self._planner.plan(
                messages=messages,
                tool_schemas=tool_schemas,
                planning_prompt="Plan the investigation. Output a structured InvestigationPlan.",
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
            })

            return {
                "cost": 0,
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
                })

                # One more reasoning round to fill gaps
                response = await self._gateway.complete_with_tools(
                    messages=messages,
                    tools=tool_schemas,
                    task=ModelTask.CLASSIFICATION,
                    model_id=tier_cfg.thinker_model,
                    timeout=settings.REASONING_TIMEOUT_SECONDS,
                )
                total_cost += response.usage.cost.total_cost if response.usage.cost else 0

                if response.has_tool_calls:
                    tool_round = await self._tools.execute_tool_round(response, patient_ids, seen_calls, patient_names=patient_names)
                    messages.append(tool_round.assistant_message)
                    messages.extend(tool_round.tool_messages)
                    total_tools += tool_round.executed_count

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
    ) -> list[dict[str, Any]]:
        """Build messages for the responder model.

        Takes the full reasoning conversation and restructures it for the
        responder: system prompt + gathered data summary + user question.
        """
        # Extract system messages, user message, and all tool results
        system_msgs: list[str] = []
        user_msg = ""
        gathered_data: list[str] = []

        for msg in reasoning_messages:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""

            if role == "system":
                system_msgs.append(content)
            elif role == "user":
                user_msg = content
            elif role == "tool":
                gathered_data.append(content)
            elif role == "assistant" and content and not msg.get("tool_calls"):
                # Thinker's analysis notes (when it stopped calling tools)
                gathered_data.append(f"Analysis notes: {content}")

        # Build responder messages
        messages: list[dict[str, Any]] = []

        # Keep original system prompts (patient context, names, facts)
        for sys_content in system_msgs:
            messages.append({"role": "system", "content": sys_content})

        # Replace reasoning prompt with response prompt
        messages.append({"role": "system", "content": response_prompt})

        # Add gathered data as context
        if gathered_data:
            data_text = "\n\n---\n\n".join(gathered_data)
            if len(data_text) > settings.MAX_ANALYSIS_CHARS:
                data_text = data_text[:settings.MAX_ANALYSIS_CHARS] + "\n... (truncated)"
            messages.append({
                "role": "system",
                "content": f"HEALTH DATA GATHERED BY INVESTIGATION:\n\n{data_text}",
            })

        messages.append({"role": "user", "content": user_msg})
        return messages

    async def _generate_final_response(
        self,
        *,
        messages: list[dict[str, Any]],
        response_prompt: str,
        model_id: str,
    ) -> Any:
        """Generate the final polished response from the responder model."""
        responder_messages = self._build_responder_messages(messages, response_prompt)
        return await self._gateway.complete(
            messages=responder_messages,
            task=ModelTask.RESPONSE_GENERATION,
            model_id=model_id,
        )

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
