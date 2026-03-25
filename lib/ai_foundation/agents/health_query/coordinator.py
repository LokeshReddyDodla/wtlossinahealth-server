"""
Coordinator — orchestrates multi-agent health query pipeline.

Pipeline for multi-domain queries:
    1. Plan (InvestigationPlanner)
    2. Dispatch to specialists in parallel
    3. Reflect on combined findings (ReflectionEngine)
    4. If gaps: targeted follow-up
    5. Hand off to responder for final response

Single-domain queries skip the coordinator and use ReasoningEngine directly.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

from lib.ai_foundation.config import settings
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.streaming.sse import (
    PipelineStage,
    SSEDonePayload,
    sse_done,
    sse_plan,
    sse_reflection,
    sse_specialist_done,
    sse_specialist_start,
    sse_status,
    sse_token,
)

from .context_loader import build_context_messages
from .reasoning_engine import ReasoningResult, ReasoningTier, TIER_CONFIGS
from .specialists import Specialist, SpecialistFindings

if TYPE_CHECKING:
    from .context_loader import AgentContext
    from .planner import InvestigationPlanner
    from .reflector import ReflectionEngine
    from .tools import ToolExecutor
    from lib.ai_foundation.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


class Coordinator:
    """Orchestrates: plan -> parallel specialists -> reflect -> respond.

    Usage::

        coordinator = Coordinator(
            gateway=gw, tool_executor=te, planner=planner,
            reflector=reflector, specialists={"glucose": ..., "nutrition": ...},
        )
        result = await coordinator.orchestrate(
            user_message="How are meals affecting my glucose?",
            ..., domains=["glucose", "nutrition"], tier=ReasoningTier.ADVANCED,
        )
    """

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        tool_executor: ToolExecutor,
        planner: InvestigationPlanner | None = None,
        reflector: ReflectionEngine | None = None,
        specialists: dict[str, Specialist] | None = None,
    ) -> None:
        self._gateway = gateway
        self._tools = tool_executor
        self._planner = planner
        self._reflector = reflector
        self._specialists = specialists or {}

    # ── Public API (unchanged signatures) ─────────────────────────────

    async def orchestrate(
        self,
        *,
        user_message: str,
        system_prompt: str,
        reasoning_prompt: str,
        response_prompt: str,
        context: AgentContext,
        patient_ids: list[str],
        domains: list[str],
        tier: ReasoningTier = ReasoningTier.STANDARD,
    ) -> ReasoningResult:
        """Full orchestration: plan -> specialists -> reflect -> respond."""
        async for item in self._orchestrate_core(
            user_message=user_message,
            system_prompt=system_prompt,
            reasoning_prompt=reasoning_prompt,
            response_prompt=response_prompt,
            context=context,
            patient_ids=patient_ids,
            domains=domains,
            tier=tier,
            emit_events=False,
        ):
            if isinstance(item, ReasoningResult):
                return item
        # Unreachable — _orchestrate_core always yields a ReasoningResult at the end.
        raise RuntimeError("_orchestrate_core did not produce a ReasoningResult")  # pragma: no cover

    async def orchestrate_stream(
        self,
        *,
        user_message: str,
        system_prompt: str,
        reasoning_prompt: str,
        response_prompt: str,
        context: AgentContext,
        patient_ids: list[str],
        domains: list[str],
        tier: ReasoningTier = ReasoningTier.STANDARD,
    ) -> AsyncIterator[str]:
        """Streaming orchestration with SSE events."""
        async for item in self._orchestrate_core(
            user_message=user_message,
            system_prompt=system_prompt,
            reasoning_prompt=reasoning_prompt,
            response_prompt=response_prompt,
            context=context,
            patient_ids=patient_ids,
            domains=domains,
            tier=tier,
            emit_events=True,
        ):
            if isinstance(item, str):
                yield item

    # ── Core loop (shared implementation) ─────────────────────────────

    async def _orchestrate_core(
        self,
        *,
        user_message: str,
        system_prompt: str,
        reasoning_prompt: str,
        response_prompt: str,
        context: AgentContext,
        patient_ids: list[str],
        domains: list[str],
        tier: ReasoningTier = ReasoningTier.STANDARD,
        emit_events: bool = False,
    ) -> AsyncIterator[str | ReasoningResult]:
        """Unified orchestration loop that yields SSE strings and/or a ReasoningResult."""
        tier_cfg = TIER_CONFIGS[tier]
        total_cost = 0.0
        total_tools = 0

        # Build base messages (shared across specialists)
        base_messages = build_context_messages(
            user_message=user_message,
            system_prompt=system_prompt,
            reasoning_prompt=reasoning_prompt,
            context=context,
        )

        if emit_events:
            yield sse_status(PipelineStage.ANALYZING, "Planning multi-domain investigation...")

        # ── 1. Planning ──
        plan = None
        if self._planner and settings.PLANNING_ENABLED:
            try:
                plan = await self._planner.plan(
                    messages=base_messages,
                    tool_schemas=self._tools.get_openai_schemas(),
                    planning_prompt="Plan the multi-domain investigation.",
                    model_id=tier_cfg.thinker_model,
                )
                if emit_events:
                    yield sse_plan(plan.strategy, len(plan.steps), plan.domains_involved)
            except Exception as exc:
                logger.warning("Coordinator planning failed (%s): %s", type(exc).__name__, exc)

        # ── 2. Dispatch specialists in parallel ──
        budget_per_specialist = max(1, tier_cfg.max_tool_calls // max(len(domains), 1))
        active_specialists: list[tuple[str, Specialist]] = []

        for domain in domains:
            specialist = self._specialists.get(domain)
            if specialist:
                active_specialists.append((domain, specialist))
                if emit_events:
                    yield sse_specialist_start(domain, budget_per_specialist)

        # Run specialists in parallel, collect findings
        if active_specialists:
            tasks = [
                spec.investigate(
                    messages=base_messages,
                    patient_ids=patient_ids,
                    max_rounds=budget_per_specialist,
                    model_id=tier_cfg.thinker_model,
                )
                for _, spec in active_specialists
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            findings: list[SpecialistFindings] = []
            for (domain, _), result in zip(active_specialists, results):
                if isinstance(result, SpecialistFindings):
                    findings.append(result)
                    total_cost += result.cost
                    total_tools += result.tool_calls_used
                    if emit_events:
                        summary = result.findings[:settings.SUMMARY_TRUNCATION_CHARS] if result.findings else "No findings"
                        yield sse_specialist_done(domain, summary)
                else:
                    logger.warning("Specialist %s failed: %s", domain, result)
                    if emit_events:
                        yield sse_specialist_done(domain, f"Error: {result}")
        else:
            findings = []

        # ── 3. Reflect on combined findings ──
        combined_data = self._combine_findings(findings)
        reflection_result = None

        if self._reflector and settings.REFLECTION_ENABLED and tier_cfg.max_tool_calls >= 10:
            try:
                reflect_messages = list(base_messages)
                reflect_messages.append({
                    "role": "system",
                    "content": f"Investigation findings:\n\n{combined_data}",
                })
                reflection_result = await self._reflector.reflect(
                    messages=reflect_messages,
                    user_question=user_message,
                    reflection_prompt="Review the multi-domain investigation.",
                    model_id=tier_cfg.thinker_model,
                )
                if emit_events:
                    yield sse_reflection(
                        reflection_result.confidence,
                        reflection_result.gaps,
                        reflection_result.is_complete,
                    )
            except Exception as exc:
                logger.warning("Coordinator reflection failed (%s): %s", type(exc).__name__, exc)

        # ── 4. Generate final response ──
        responder_messages = self._build_responder_messages(
            base_messages=base_messages,
            response_prompt=response_prompt,
            combined_data=combined_data,
            reflection=reflection_result,
        )

        if emit_events:
            # Stream final response
            yield sse_status(PipelineStage.GENERATING_RESPONSE, "Building personalized insights...")

            full_response_parts: list[str] = []

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

            yield sse_done(SSEDonePayload(
                cost_usd=total_cost,
                data={
                    "rounds_used": len(findings),
                    "tools_called": total_tools,
                    "tier": tier.value,
                    "domains": domains,
                    "full_response": "".join(full_response_parts),
                },
            ))
        else:
            # Non-streaming: single responder call
            final_response = await self._gateway.complete(
                messages=responder_messages,
                task=ModelTask.RESPONSE_GENERATION,
                model_id=tier_cfg.responder_model,
            )
            total_cost += final_response.usage.cost.total_cost if final_response.usage.cost else 0

            yield ReasoningResult(
                response=final_response.content or "",
                steps=[],
                rounds_used=len(findings),
                tools_called=total_tools,
                total_cost=total_cost,
                thinker_model=tier_cfg.thinker_model,
                responder_model=tier_cfg.responder_model,
                tier=tier.value,
            )

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _combine_findings(findings: list[SpecialistFindings]) -> str:
        """Combine findings from multiple specialists into a single text block."""
        if not findings:
            return "No data gathered."

        sections: list[str] = []
        for f in findings:
            header = f.domain.upper().replace("_", " ")
            sections.append(f"## {header} FINDINGS\n\n{f.findings}")

        return "\n\n---\n\n".join(sections)

    @staticmethod
    def _build_responder_messages(
        *,
        base_messages: list[dict[str, Any]],
        response_prompt: str,
        combined_data: str,
        reflection: Any = None,
    ) -> list[dict[str, Any]]:
        """Build messages for the responder model."""
        messages: list[dict[str, Any]] = []

        # Keep system messages from base (system prompt, context)
        for msg in base_messages:
            if msg.get("role") == "system":
                messages.append(msg)

        messages.append({"role": "system", "content": response_prompt})

        # Add combined investigation data
        data_text = combined_data
        if len(data_text) > settings.MAX_ANALYSIS_CHARS:
            data_text = data_text[:settings.MAX_ANALYSIS_CHARS] + "\n... (truncated)"
        messages.append({
            "role": "system",
            "content": f"HEALTH DATA FROM MULTI-DOMAIN INVESTIGATION:\n\n{data_text}",
        })

        # Add safety concerns from reflection
        if reflection and hasattr(reflection, "safety_concerns") and reflection.safety_concerns:
            concerns = "\n".join(f"- {c}" for c in reflection.safety_concerns)
            messages.append({
                "role": "system",
                "content": f"SAFETY NOTE — mention these concerns:\n{concerns}",
            })

        # Add user message
        for msg in base_messages:
            if msg.get("role") == "user":
                messages.append(msg)
                break

        return messages
