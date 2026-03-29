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
        patient_names: dict[str, str] | None = None,
        user_role: str = "patient",
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
            patient_names=patient_names,
            user_role=user_role,
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
        patient_names: dict[str, str] | None = None,
        user_role: str = "patient",
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
            patient_names=patient_names,
            user_role=user_role,
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
        patient_names: dict[str, str] | None = None,
        user_role: str = "patient",
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
                    patient_names=patient_names,
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
                    "_meta": {"type": "gathered_data"},
                })
                reflect_messages = self._prune_for_budget(reflect_messages, tier_cfg.thinker_model)
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
            findings=findings,
            user_role=user_role,
        )

        responder_messages = self._prune_for_budget(responder_messages, tier_cfg.responder_model)

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

    # ── Context window protection ────────────────────────────────────

    def _prune_for_budget(self, messages: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
        """Ensure messages fit within model's context window.

        Simpler than ReasoningEngine's 5-strategy pruner — the Coordinator's
        messages are already structured (base + combined_data + evidence).
        Strategy: repeatedly halve the longest non-critical message until under budget.
        """
        budget = self._get_input_budget(model)
        tokens = self._gateway.count_tokens(messages, model)

        if tokens <= budget:
            return messages

        logger.info("Coordinator token budget exceeded: %d/%d — truncating", tokens, budget)
        messages = list(messages)  # copy once

        _PROTECTED = frozenset({"instruction", "evidence_summary", "user_question"})
        max_iterations = 5  # safety limit

        for _ in range(max_iterations):
            # Find the longest non-critical message
            longest_idx = -1
            longest_len = 0
            for i, msg in enumerate(messages):
                if msg.get("_meta", {}).get("type") in _PROTECTED:
                    continue
                content_len = len(msg.get("content", "") or "")
                if content_len > longest_len:
                    longest_len = content_len
                    longest_idx = i

            if longest_idx < 0 or longest_len <= 500:
                break  # nothing left to truncate

            # Halve the longest message
            target = max(longest_len // 2, 500)
            msg = messages[longest_idx]
            messages[longest_idx] = {
                **msg,
                "content": msg["content"][:target] + "\n... (truncated to fit context window)",
            }

            tokens = self._gateway.count_tokens(messages, model)
            logger.info("Coordinator prune: %d tokens (%.0f%%)", tokens, tokens / max(budget, 1) * 100)
            if tokens <= budget:
                return messages

        logger.warning("Coordinator pruning exhausted — still at %d/%d tokens", tokens, budget)
        return messages  # best effort

    def _get_input_budget(self, model: str) -> int:
        """Calculate the max input tokens for a model."""
        window = self._gateway.get_model_window(model)
        return min(
            int(window * settings.CONTEXT_BUDGET_RATIO),
            window - settings.CONTEXT_RESPONSE_RESERVE,
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
        findings: list | None = None,
        user_role: str = "patient",
    ) -> list[dict[str, Any]]:
        """Build messages for the responder model."""
        from lib.ai_foundation.agents.health_query.evidence import (
            build_summary_from_findings,
            format_patient,
            format_provider,
        )

        messages: list[dict[str, Any]] = []

        # Keep system messages from base (system prompt, context)
        for msg in base_messages:
            if msg.get("role") == "system":
                messages.append(msg)

        messages.append({"role": "system", "content": response_prompt, "_meta": {"type": "instruction"}})

        # Add combined investigation data
        data_text = combined_data
        if len(data_text) > settings.MAX_ANALYSIS_CHARS:
            data_text = data_text[:settings.MAX_ANALYSIS_CHARS] + "\n... (truncated)"
        messages.append({
            "role": "system",
            "content": f"HEALTH DATA FROM MULTI-DOMAIN INVESTIGATION:\n\n{data_text}",
            "_meta": {"type": "gathered_data"},
        })

        # Add safety concerns from reflection
        if reflection and hasattr(reflection, "safety_concerns") and reflection.safety_concerns:
            concerns = "\n".join(f"- {c}" for c in reflection.safety_concerns)
            messages.append({
                "role": "system",
                "content": f"SAFETY NOTE — mention these concerns:\n{concerns}",
                "_meta": {"type": "reflection"},
            })

        # Inject evidence summary from specialist findings
        if findings:
            summary = build_summary_from_findings(findings)
            evidence_text = format_provider(summary) if user_role in ("care_provider", "admin") else format_patient(summary)
            if evidence_text:
                messages.append({
                    "role": "system",
                    "content": f"INVESTIGATION EVIDENCE:\n{evidence_text}",
                    "_meta": {"type": "evidence_summary"},
                })

        # Add user message (the actual question, not history)
        for msg in reversed(base_messages):
            if msg.get("role") == "user" and msg.get("_meta", {}).get("type") == "user_question":
                messages.append(msg)
                break

        return messages
