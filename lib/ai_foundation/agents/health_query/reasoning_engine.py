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

    # ── Non-streaming ──────────────────────────────────────────────────

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
    ) -> ReasoningResult:
        """Run the full reasoning loop and return the result."""
        tier_cfg = TIER_CONFIGS[tier]
        tool_schemas = self._tools.get_openai_schemas()
        messages = self._build_initial_messages(
            user_message, system_prompt, reasoning_prompt, context,
        )

        steps: list[ReasoningStep] = []
        total_cost = 0.0
        total_tools = 0
        seen_calls: set[str] = set()  # deduplication
        budget_remaining = tier_cfg.max_tool_calls

        # ── Planning phase (STANDARD+ tiers) ──
        if self._planner and settings.PLANNING_ENABLED and tier_cfg.max_tool_calls > 2:
            plan = await self._execute_plan(
                messages=messages,
                tool_schemas=tool_schemas,
                tier_cfg=tier_cfg,
                patient_ids=patient_ids,
                seen_calls=seen_calls,
            )
            total_cost += plan["cost"]
            total_tools += plan["tools_called"]
            budget_remaining -= plan["tools_called"]
            if plan["steps"]:
                steps.extend(plan["steps"])

        for round_num in range(1, budget_remaining + 1):
            response = await self._gateway.complete_with_tools(
                messages=messages,
                tools=tool_schemas,
                task=ModelTask.CLASSIFICATION,
                model_id=tier_cfg.thinker_model,
                timeout=settings.REASONING_TIMEOUT_SECONDS,
            )
            total_cost += response.usage.cost.total_cost if response.usage.cost else 0

            if not response.has_tool_calls:
                # LLM decided it has enough data — capture final thought
                if response.content:
                    steps.append(ReasoningStep(
                        round=round_num, thought=response.content,
                    ))
                break

            step = ReasoningStep(round=round_num, thought=response.content)

            # Build assistant message with tool calls (OpenAI format)
            assistant_msg = self._build_assistant_tool_call_msg(response)
            messages.append(assistant_msg)

            # Partition tool calls: new vs duplicate
            to_execute: list[tuple[ToolCall, str]] = []  # (tc, call_key)
            duplicate_tcs: list[ToolCall] = []
            for tc in response.tool_calls:
                call_key = f"{tc.function_name}:{json.dumps(tc.arguments, sort_keys=True)}"
                if call_key in seen_calls:
                    duplicate_tcs.append(tc)
                else:
                    seen_calls.add(call_key)
                    to_execute.append((tc, call_key))

            # Execute all non-duplicate calls in parallel
            if to_execute:
                results = await self._tools.execute_parallel(
                    [(tc.function_name, tc.arguments) for tc, _ in to_execute],
                    patient_ids,
                )
                total_tools += len(to_execute)
            else:
                results = []

            # Build messages: first the parallel results
            for (tc, _), result_text in zip(to_execute, results):
                step.tool_calls.append({"tool": tc.function_name, "args": tc.arguments})
                step.tool_results.append({"tool": tc.function_name, "result": result_text[:500]})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

            # Then the duplicate warnings
            for tc in duplicate_tcs:
                dup_msg = "You already fetched this exact data. Try a different tool or different parameters."
                step.tool_calls.append({"tool": tc.function_name, "args": tc.arguments})
                step.tool_results.append({"tool": tc.function_name, "result": dup_msg})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": dup_msg,
                })

            steps.append(step)
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
            )
            total_cost = reflection["total_cost"]
            total_tools = reflection["total_tools"]

        # ── Final response from responder model ──
        final_response = await self._generate_final_response(
            messages=messages,
            response_prompt=response_prompt,
            model_id=tier_cfg.responder_model,
        )
        total_cost += final_response.usage.cost.total_cost if final_response.usage.cost else 0

        return ReasoningResult(
            response=final_response.content or "",
            steps=steps,
            rounds_used=len(steps),
            tools_called=total_tools,
            total_cost=total_cost,
            thinker_model=tier_cfg.thinker_model,
            responder_model=tier_cfg.responder_model,
            tier=tier.value,
        )

    # ── Streaming ──────────────────────────────────────────────────────

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
    ) -> AsyncIterator[str]:
        """Run the reasoning loop, yielding SSE events as the doctor thinks."""
        tier_cfg = TIER_CONFIGS[tier]
        tool_schemas = self._tools.get_openai_schemas()
        messages = self._build_initial_messages(
            user_message, system_prompt, reasoning_prompt, context,
        )

        total_cost = 0.0
        total_tools = 0
        rounds_used = 0
        seen_calls: set[str] = set()
        budget_remaining = tier_cfg.max_tool_calls

        yield sse_status(PipelineStage.ANALYZING, "Investigating your health data...")

        # ── Planning phase (STANDARD+ tiers) ──
        if self._planner and settings.PLANNING_ENABLED and tier_cfg.max_tool_calls > 2:
            plan = await self._execute_plan(
                messages=messages,
                tool_schemas=tool_schemas,
                tier_cfg=tier_cfg,
                patient_ids=patient_ids,
                seen_calls=seen_calls,
            )
            total_cost += plan["cost"]
            total_tools += plan["tools_called"]
            budget_remaining -= plan["tools_called"]

            # Emit plan event
            if plan.get("plan_obj"):
                yield sse_plan(
                    plan["plan_obj"].strategy,
                    len(plan["plan_obj"].steps),
                    plan["plan_obj"].domains_involved,
                )

        for round_num in range(1, budget_remaining + 1):
            response = await self._gateway.complete_with_tools(
                messages=messages,
                tools=tool_schemas,
                task=ModelTask.CLASSIFICATION,
                model_id=tier_cfg.thinker_model,
                timeout=settings.REASONING_TIMEOUT_SECONDS,
            )
            total_cost += response.usage.cost.total_cost if response.usage.cost else 0

            if not response.has_tool_calls:
                if tier_cfg.show_reasoning and response.content:
                    yield sse_reasoning(round_num, response.content)
                rounds_used = round_num
                break

            # Emit reasoning thought
            if tier_cfg.show_reasoning and response.content:
                yield sse_reasoning(round_num, response.content)

            # Build assistant message
            assistant_msg = self._build_assistant_tool_call_msg(response)
            messages.append(assistant_msg)

            # Partition: new vs duplicate
            to_execute: list[tuple[ToolCall, str]] = []
            duplicate_tcs: list[ToolCall] = []
            for tc in response.tool_calls:
                call_key = f"{tc.function_name}:{json.dumps(tc.arguments, sort_keys=True)}"
                if call_key in seen_calls:
                    duplicate_tcs.append(tc)
                else:
                    seen_calls.add(call_key)
                    to_execute.append((tc, call_key))

            # Emit all tool_call events upfront (user sees what's being fetched)
            if tier_cfg.show_reasoning:
                for tc, _ in to_execute:
                    yield sse_tool_call(tc.function_name, tc.arguments)

            # Execute all non-duplicate calls in parallel
            if to_execute:
                results = await self._tools.execute_parallel(
                    [(tc.function_name, tc.arguments) for tc, _ in to_execute],
                    patient_ids,
                )
                total_tools += len(to_execute)
            else:
                results = []

            # Emit results and build messages
            for (tc, _), result_text in zip(to_execute, results):
                if tier_cfg.show_reasoning:
                    summary = self._summarize_result(tc.function_name, result_text)
                    yield sse_tool_result(tc.function_name, summary)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

            # Handle duplicates
            for tc in duplicate_tcs:
                dup_msg = "You already fetched this exact data. Try a different tool or different parameters."
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": dup_msg,
                })

            rounds_used = round_num
        else:
            messages.append({
                "role": "system",
                "content": (
                    "You have reached the maximum number of investigation rounds. "
                    "Generate your best response with the data you have gathered so far."
                ),
            })

        # ── Reflection (ADVANCED+ tiers) ──
        if self._reflector and settings.REFLECTION_ENABLED and tier_cfg.max_tool_calls >= 10:
            reflection = await self._reflect_and_followup(
                messages=messages,
                user_message=user_message,
                tool_schemas=tool_schemas,
                tier_cfg=tier_cfg,
                patient_ids=patient_ids,
                seen_calls=seen_calls,
                steps=[],  # streaming doesn't track steps
                total_cost=total_cost,
                total_tools=total_tools,
            )
            total_cost = reflection["total_cost"]
            total_tools = reflection["total_tools"]

            if reflection.get("result"):
                r = reflection["result"]
                yield sse_reflection(r.confidence, r.gaps, r.is_complete)

        # ── Stream final response ──
        yield sse_status(
            PipelineStage.GENERATING_RESPONSE,
            "Building your personalized insights...",
        )

        # Build responder messages
        responder_messages = self._build_responder_messages(messages, response_prompt)

        async for chunk in self._gateway.stream(
            messages=responder_messages,
            task=ModelTask.RESPONSE_GENERATION,
            model_id=tier_cfg.responder_model,
        ):
            if chunk.delta:
                yield sse_token(chunk.delta)
            if chunk.finished and chunk.usage:
                total_cost += chunk.usage.cost.total_cost if chunk.usage.cost else 0

        yield sse_done(SSEDonePayload(
            cost_usd=total_cost,
            data={
                "rounds_used": rounds_used,
                "tools_called": total_tools,
                "tier": tier.value,
            },
        ))

    # ── Planning ───────────────────────────────────────────────────────

    async def _execute_plan(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        tier_cfg: TierConfig,
        patient_ids: list[str],
        seen_calls: set[str],
    ) -> dict[str, Any]:
        """Generate and execute Phase 1 of the investigation plan.

        Returns dict with: cost, tools_called, steps, plan_obj.
        """
        try:
            # Get planning prompt
            planning_prompt = ""
            try:
                from lib.ai_foundation.prompts.registry import PromptRegistry
                # The prompt is loaded by the agent and passed in messages[1]
                # We use a simple fallback if not available
            except Exception:
                pass

            plan = await self._planner.plan(
                messages=messages,
                tool_schemas=tool_schemas,
                planning_prompt="Plan the investigation. Output a structured InvestigationPlan.",
                model_id=tier_cfg.thinker_model,
            )

            # Execute Phase 1 steps in parallel
            phase1 = [s for s in plan.steps if s.phase == 1]
            if not phase1:
                return {"cost": 0, "tools_called": 0, "steps": [], "plan_obj": plan}

            # Build calls and execute
            calls: list[tuple[str, dict[str, Any]]] = []
            for step in phase1:
                call_key = f"{step.tool_name}:{json.dumps(step.arguments, sort_keys=True)}"
                if call_key not in seen_calls:
                    seen_calls.add(call_key)
                    calls.append((step.tool_name, step.arguments))

            if not calls:
                return {"cost": 0, "tools_called": 0, "steps": [], "plan_obj": plan}

            results = await self._tools.execute_parallel(calls, patient_ids)

            # Build a synthetic reasoning step for the plan execution
            plan_step = ReasoningStep(
                round=0,
                thought=f"Investigation plan: {plan.strategy}",
                tool_calls=[{"tool": name, "args": args} for name, args in calls],
                tool_results=[
                    {"tool": name, "result": result[:500]}
                    for (name, _), result in zip(calls, results)
                ],
            )

            # Add plan context and results to the conversation
            # We use a synthetic assistant message explaining the plan
            messages.append({
                "role": "assistant",
                "content": (
                    f"I've planned my investigation: {plan.strategy}\n"
                    f"Phase 1 results are now available. "
                    f"Let me analyze what I found and decide on next steps."
                ),
            })

            # Add tool results as system context (not tool messages, since there's no tool_call)
            result_parts = []
            for (name, args), result in zip(calls, results):
                result_parts.append(f"[{name}] {result}")
            messages.append({
                "role": "system",
                "content": "Phase 1 investigation results:\n\n" + "\n\n---\n\n".join(result_parts),
            })

            return {
                "cost": 0,  # Planning extraction cost tracked separately
                "tools_called": len(calls),
                "steps": [plan_step],
                "plan_obj": plan,
            }

        except Exception as exc:
            logger.warning("Planning failed, falling back to adaptive loop: %s", exc)
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
                    assistant_msg = self._build_assistant_tool_call_msg(response)
                    messages.append(assistant_msg)

                    to_execute = []
                    for tc in response.tool_calls:
                        call_key = f"{tc.function_name}:{json.dumps(tc.arguments, sort_keys=True)}"
                        if call_key not in seen_calls:
                            seen_calls.add(call_key)
                            to_execute.append((tc.function_name, tc.arguments, tc.id))

                    if to_execute:
                        results = await self._tools.execute_parallel(
                            [(name, args) for name, args, _ in to_execute],
                            patient_ids,
                        )
                        total_tools += len(to_execute)

                        for (name, args, tc_id), result_text in zip(to_execute, results):
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": result_text,
                            })

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
            logger.warning("Reflection failed, proceeding without: %s", exc)
            return {
                "total_cost": total_cost,
                "total_tools": total_tools,
                "result": None,
            }

    # ── Message Builders ───────────────────────────────────────────────

    def _build_initial_messages(
        self,
        user_message: str,
        system_prompt: str,
        reasoning_prompt: str,
        context: AgentContext,
    ) -> list[dict[str, Any]]:
        """Build the initial message array for the thinker."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": reasoning_prompt},
        ]

        # Pre-load patient context (profile + facts + names)
        context_parts: list[str] = []
        if context.patient_names:
            names = [f"- {pid}: {name}" for pid, name in context.patient_names.items()]
            context_parts.append("Patient names:\n" + "\n".join(names))
        if context.facts:
            facts = [f"- {f['key']}: {f['value']}" for f in context.facts[:10]]
            context_parts.append("Known patient facts:\n" + "\n".join(facts))
        if context.thread_summary:
            context_parts.append(f"Conversation summary:\n{context.thread_summary}")

        if context_parts:
            messages.append({
                "role": "system",
                "content": "PATIENT CONTEXT (pre-loaded):\n\n" + "\n\n".join(context_parts),
            })

        # Add conversation history
        messages.extend(context.history[-8:])

        # User's question
        messages.append({"role": "user", "content": user_message})

        return messages

    @staticmethod
    def _build_assistant_tool_call_msg(response: LLMToolResponse) -> dict[str, Any]:
        """Build an assistant message with tool_calls in OpenAI format."""
        msg: dict[str, Any] = {
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
        }
        return msg

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
            return result[:200] + "..."
        return result
