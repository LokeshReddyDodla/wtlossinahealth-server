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
import re
from typing import TYPE_CHECKING, Any, AsyncIterator

from lib.ai_foundation.config import settings
from lib.ai_foundation.models.gateway import safe_cost
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.streaming.sse import (
    PipelineStage,
    SSEDonePayload,
    sse_error,
    sse_plan,
    sse_reflection,
    sse_specialist_done,
    sse_specialist_start,
    sse_status,
    sse_bubble,
    sse_token,
)

from lib.ai_foundation.agents.health_query.evidence import (
    build_summary_from_findings,
    compute_coverage_confidence,
    detect_conflicts,
    format_data_gaps,
)

from lib.ai_foundation.agents.core.bubbles import BubbleStreamFilter
from lib.ai_foundation.agents.core.chart_processor import process_charts
from lib.ai_foundation.agents.core.context_loader import build_context_messages
from lib.ai_foundation.agents.core.context_pruner import ContextPruner, MIN_TRUNCATION_CHARS as _MIN_TRUNCATION_CHARS
from .reasoning_engine import ReasoningResult, ReasoningTier, TIER_CONFIGS
from .specialists import Specialist, SpecialistFindings

if TYPE_CHECKING:
    from lib.ai_foundation.agents.core.context_loader import AgentContext
    from .planner import InvestigationPlanner
    from .reflector import ReflectionEngine
    from .tools import ToolExecutor
    from lib.ai_foundation.models.gateway import ModelGateway

logger = logging.getLogger(__name__)

# ── Regex cue patterns for cross-domain connection detection ─────────────
_GLUCOSE_SPIKE_CUES = re.compile(r"\b(?:spike|hyper|elevated|high glucose|above range)")
_GLUCOSE_VARIABILITY_CUES = re.compile(r"\b(?:variab|unstable|fluctuat|inconsistent)")
_GLUCOSE_IMPROVED_CUES = re.compile(r"\b(?:improved|better|lower average|good control)")
_NUTRITION_MEAL_CUES = re.compile(r"\b(?:carb|high.?carb|meal|calories|protein|dinner|lunch|breakfast)")
_FITNESS_LOW_CUES = re.compile(r"\b(?:low activity|inactive|sedentary|few steps|minimal activity|barely moved)")
_FITNESS_ACTIVE_CUES = re.compile(r"\b(?:active|exercise|workout|walking|running|high activity|good activity)")
_SLEEP_POOR_CUES = re.compile(r"\b(?:poor sleep|short sleep|disrupted|insomnia|restless|waking)")
_HIGH_CAL_CUES = re.compile(r"\b(?:high calori|excess|over.?eat)")
_NEGATION_PREFIX = re.compile(r"\b(?:no|not|without|zero|none)\s+")


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
        self._pruner = ContextPruner(gateway=gateway)

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
        trace_id: str | None = None,
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
            trace_id=trace_id,
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
        trace_id: str | None = None,
    ) -> AsyncIterator[str | SSEDonePayload]:
        """Streaming orchestration with SSE events.

        Yields formatted SSE strings, then a terminal SSEDonePayload carrying
        the structured result (full response, cost, evidence metrics).
        """
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
            trace_id=trace_id,
        ):
            if isinstance(item, (str, SSEDonePayload)):
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
        trace_id: str | None = None,
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
        plan_cost = 0.0
        if self._planner and settings.PLANNING_ENABLED:
            try:
                _meta = getattr(context, "metadata", None) or {}
                is_voice = _meta.get("output_mode") == "voice"
                planning_prompt = (
                    "Plan the multi-domain investigation. "
                    "Write the strategy field as if you are a doctor explaining your plan "
                    "to the patient out loud — first person, conversational, no jargon."
                ) if is_voice else "Plan the multi-domain investigation."

                plan, plan_cost = await self._planner.plan(
                    messages=base_messages,
                    tool_schemas=self._tools.get_openai_schemas(),
                    planning_prompt=planning_prompt,
                    model_id=tier_cfg.thinker_model,
                )
                total_cost += plan_cost
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

        # Run specialists in parallel, collect findings. Timeout is applied
        # per specialist so one straggler can't discard finished work.
        if active_specialists:
            tasks = [
                asyncio.wait_for(
                    spec.investigate(
                        messages=base_messages,
                        patient_ids=patient_ids,
                        max_rounds=budget_per_specialist,
                        model_id=tier_cfg.thinker_model,
                        patient_names=patient_names,
                        trace_id=trace_id,
                    ),
                    timeout=settings.SPECIALIST_TIMEOUT_SECONDS,
                )
                for _, spec in active_specialists
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            findings: list[SpecialistFindings] = []
            failed_domains: list[str] = []
            for (domain, _), result in zip(active_specialists, results):
                if isinstance(result, SpecialistFindings):
                    findings.append(result)
                    total_cost += result.cost
                    total_tools += result.tool_calls_used
                    if emit_events:
                        summary = result.findings[:settings.SUMMARY_TRUNCATION_CHARS] if result.findings else "No findings"
                        yield sse_specialist_done(domain, summary)
                else:
                    failed_domains.append(domain)
                    logger.warning("Specialist %s failed: %s", domain, result)
                    if emit_events:
                        yield sse_specialist_done(domain, f"Error: {result}")
        else:
            findings = []
            failed_domains = []

        # ── 3. Reflect on combined findings ──
        combined_data, cross_domain_connections = self._combine_findings(findings)
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

        # ── 3.5. Cross-domain synthesis (ADVANCED+ tiers) ──
        if (
            settings.CROSS_DOMAIN_SYNTHESIS_ENABLED
            and tier_cfg.max_tool_calls >= 10
            and (cross_domain_connections or (reflection_result and not reflection_result.is_complete))
        ):
            try:
                synthesis = await self._cross_domain_synthesis(
                    base_messages=base_messages,
                    combined_data=combined_data,
                    cross_domain_connections=cross_domain_connections,
                    reflection_result=reflection_result,
                    user_message=user_message,
                    tier_cfg=tier_cfg,
                    patient_ids=patient_ids,
                    patient_names=patient_names,
                )
                if synthesis["findings"]:
                    combined_data += f"\n\n---\n\n## CROSS-DOMAIN ANALYSIS\n\n{synthesis['findings']}"
                total_cost += synthesis["cost"]
                total_tools += synthesis["tools_called"]
                if emit_events:
                    yield sse_status(PipelineStage.ANALYZING, "Cross-domain analysis complete.")
            except Exception as exc:
                logger.warning("Cross-domain synthesis failed (%s): %s", type(exc).__name__, exc)

        # ── 4. Generate final response ──
        responder_messages = self._build_responder_messages(
            base_messages=base_messages,
            response_prompt=response_prompt,
            combined_data=combined_data,
            reflection=reflection_result,
            findings=findings,
            user_role=user_role,
            failed_domains=failed_domains,
        )

        responder_messages = self._prune_for_budget(responder_messages, tier_cfg.responder_model)

        if emit_events:
            # Stream final response
            yield sse_status(PipelineStage.GENERATING_RESPONSE, "Building personalized insights...")

            full_response_parts: list[str] = []
            # Visible stream never carries the bubble sentinel (see
            # reasoning_engine — same protocol).
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
                        for kind, piece in bubble_filter.feed_events(chunk.delta):
                            if kind == "bubble":
                                yield sse_bubble()
                            elif piece:
                                yield sse_token(piece)
                    if chunk.finished and chunk.usage:
                        total_cost += safe_cost(chunk)
            except Exception as exc:
                logger.error(
                    "Coordinator responder stream failed after %d chunks: %s",
                    len(full_response_parts), exc,
                )
                yield sse_error(
                    message="The response was interrupted. Please try again.",
                    code="stream_error",
                    fallback_text="".join(full_response_parts) or None,
                )
                return

            tail = bubble_filter.flush()
            if tail:
                yield sse_token(tail)

            # Compute evidence confidence for SSE done payload
            evidence = self._compute_evidence_metrics(findings, reflection_result)

            # Yield the structured payload — the agent builds the final done
            # event itself (no serialize → string-parse → re-serialize round-trip).
            yield SSEDonePayload(
                cost_usd=total_cost,
                data={
                    "rounds_used": len(findings),
                    "tools_called": total_tools,
                    "tier": tier.value,
                    "domains": domains,
                    "full_response": process_charts("".join(full_response_parts)),
                    **evidence,
                },
            )
        else:
            # Non-streaming: single responder call. Explicit timeout — the
            # spec default (15s) is too tight for long multi-domain answers,
            # and explicit model_id disables fallback, so a timeout here
            # fails the whole query.
            final_response = await self._gateway.complete(
                messages=responder_messages,
                task=ModelTask.RESPONSE_GENERATION,
                model_id=tier_cfg.responder_model,
                timeout=settings.RESPONDER_TIMEOUT_SECONDS,
            )
            total_cost += safe_cost(final_response)

            # Compute evidence confidence from specialist findings
            evidence = self._compute_evidence_metrics(findings, reflection_result)

            yield ReasoningResult(
                response=process_charts(final_response.content or ""),
                steps=[],
                rounds_used=len(findings),
                tools_called=total_tools,
                total_cost=total_cost,
                thinker_model=tier_cfg.thinker_model,
                responder_model=tier_cfg.responder_model,
                tier=tier.value,
                **evidence,
            )

    # ── Evidence metrics (shared by streaming + non-streaming) ────────

    @staticmethod
    def _compute_evidence_metrics(
        findings: list[SpecialistFindings],
        reflection_result: Any,
    ) -> dict[str, Any]:
        """Compute evidence metrics from specialist findings and reflection.

        Returns dict with keys: coverage_confidence, reflection_confidence,
        data_gaps, data_conflicts.
        """
        summary = build_summary_from_findings(findings) if findings else None
        return {
            "coverage_confidence": compute_coverage_confidence(summary, skip_date_penalty=True) if summary else None,
            "reflection_confidence": reflection_result.confidence if reflection_result else None,
            "data_gaps": format_data_gaps(summary) if summary else None,
            "data_conflicts": (detect_conflicts(summary.items) if summary and summary.items else None) or None,
        }

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

            if longest_idx < 0 or longest_len <= _MIN_TRUNCATION_CHARS:
                break  # nothing left to truncate

            # Halve the longest message
            target = max(longest_len // 2, _MIN_TRUNCATION_CHARS)
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

    # ── Cross-domain synthesis ─────────────────────────────────────────

    async def _cross_domain_synthesis(
        self,
        *,
        base_messages: list[dict[str, Any]],
        combined_data: str,
        cross_domain_connections: str,
        reflection_result: Any,
        user_message: str,
        tier_cfg: Any,
        patient_ids: list[str],
        patient_names: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """LLM-driven cross-domain follow-up after specialists complete.

        The thinker sees all specialist findings and can make 1-2 tool calls
        across domain boundaries to investigate correlations.
        """
        tool_schemas = self._tools.get_openai_schemas()
        seen_calls: set[str] = set()

        # Build synthesis context
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": (
                "You are a cross-domain health data analyst. Multiple domain specialists "
                "have already investigated independently. You now see ALL their findings.\n\n"
                "Your job: identify and investigate connections between domains that individual "
                "specialists could not see. Focus on:\n"
                "- Temporal correlations (meal timing → glucose spike timing)\n"
                "- Activity level → glucose control relationships\n"
                "- Sleep quality → next-day glucose patterns\n"
                "- Medication/document changes → health metric shifts\n\n"
                "Make 1-2 TARGETED tool calls to verify cross-domain hypotheses. "
                "Do NOT re-investigate what specialists already covered."
            )},
        ]

        # Add patient context from base messages
        for msg in base_messages:
            meta = msg.get("_meta", {})
            if meta.get("type") in ("context", "fact"):
                messages.append(msg)

        # Add specialist findings
        messages.append({
            "role": "system",
            "content": f"SPECIALIST FINDINGS:\n\n{combined_data}",
        })

        # Add detected connections as hypotheses to investigate
        if cross_domain_connections:
            messages.append({
                "role": "system",
                "content": f"POSSIBLE CONNECTIONS (verify with data):\n{cross_domain_connections}",
            })

        # Add reflection gaps if any
        if reflection_result and reflection_result.gaps:
            gap_text = "\n".join(f"- {g}" for g in reflection_result.gaps)
            messages.append({
                "role": "system",
                "content": f"INVESTIGATION GAPS:\n{gap_text}",
            })

        messages.append({"role": "user", "content": user_message})

        # Prune before sending
        messages = self._prune_for_budget(messages, tier_cfg.thinker_model)

        # Run thinker loop with limited budget
        synthesis_parts: list[str] = []
        cost = 0.0
        tools_called = 0
        max_calls = settings.CROSS_DOMAIN_MAX_TOOL_CALLS

        for round_num in range(1, max_calls + 1):
            response = await self._gateway.complete_with_tools(
                messages=messages,
                tools=tool_schemas,
                task=ModelTask.CLASSIFICATION,
                model_id=tier_cfg.thinker_model,
                timeout=settings.REASONING_TIMEOUT_SECONDS,
            )
            cost += safe_cost(response)

            if not response.has_tool_calls:
                if response.content:
                    synthesis_parts.append(response.content)
                break

            # Execute tools
            tool_round = await self._tools.execute_tool_round(response, patient_ids, seen_calls, patient_names=patient_names)
            messages.append(tool_round.assistant_message)
            messages.extend(tool_round.tool_messages)
            tools_called += tool_round.executed_count

            # Collect tool results
            for result_text in tool_round.results:
                if result_text and not result_text.startswith("[NO_DATA]"):
                    synthesis_parts.append(result_text)

            if response.content:
                synthesis_parts.append(f"Analysis: {response.content}")

        findings = "\n\n".join(synthesis_parts) if synthesis_parts else ""
        if findings:
            logger.info("Cross-domain synthesis: %d tool calls, found %d chars of analysis", tools_called, len(findings))

        return {"findings": findings, "cost": cost, "tools_called": tools_called}

    def _get_input_budget(self, model: str) -> int:
        return self._pruner.get_input_budget(model)

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _combine_findings(findings: list[SpecialistFindings]) -> tuple[str, str]:
        """Combine findings from multiple specialists into a single text block.

        Appends a POSSIBLE CROSS-DOMAIN CONNECTIONS section when deterministic
        pattern matching detects overlapping health signals across domains.
        """
        if not findings:
            return "No data gathered.", ""

        sections: list[str] = []
        for f in findings:
            header = f.domain.upper().replace("_", " ")
            sections.append(f"## {header} FINDINGS\n\n{f.findings}")

        combined = "\n\n---\n\n".join(sections)

        # Append cross-domain hypotheses if detected
        connections = Coordinator._detect_cross_domain_connections(findings)
        if connections:
            combined += f"\n\n---\n\n## POSSIBLE CROSS-DOMAIN CONNECTIONS\n\n{connections}"

        return combined, connections

    @staticmethod
    def _detect_cross_domain_connections(findings: list[SpecialistFindings]) -> str:
        """Scan specialist findings for known health correlations.

        Domain-driven: both domains must be present AND each must contain
        matching cue patterns. Returns hypothesis text or empty string.
        Never asserts causation — phrased as "check the correlation."
        """
        # Index findings by domain
        by_domain: dict[str, str] = {}
        for f in findings:
            if f.findings:
                by_domain[f.domain] = f.findings.lower()

        if len(by_domain) < 2:
            return ""

        # Negation guard — if the cue word appears only in negated context, skip
        def _has_cue(text: str, cue_pattern: re.Pattern, negation_sensitive: bool = False) -> bool:
            """Check if text contains a cue pattern, optionally filtering negations."""
            matches = list(cue_pattern.finditer(text))
            if not matches:
                return False
            if not negation_sensitive:
                return True
            # Return True if ANY match is not preceded by a negation
            for match in matches:
                start = max(0, match.start() - 15)
                prefix = text[start:match.start()]
                if not _NEGATION_PREFIX.search(prefix):
                    return True
            return False

        connections: list[str] = []

        # All cue checks are negation-sensitive — "not elevated", "no poor sleep",
        # "not sedentary" should not trigger connections.
        _NS = True  # shorthand for negation_sensitive

        # Rule 1: glucose spikes + nutrition meals
        if "glucose" in by_domain and "nutrition" in by_domain:
            if _has_cue(by_domain["glucose"], _GLUCOSE_SPIKE_CUES, _NS) and _has_cue(by_domain["nutrition"], _NUTRITION_MEAL_CUES, _NS):
                connections.append(
                    "- **glucose + nutrition** — Spike/elevated language in glucose findings "
                    "and meal/carb data in nutrition findings. Check meal timing against "
                    "spike timing for possible dietary triggers."
                )

        # Rule 2: glucose elevated + fitness low
        if "glucose" in by_domain and "fitness" in by_domain:
            g = by_domain["glucose"]
            f = by_domain["fitness"]
            if (_has_cue(g, _GLUCOSE_SPIKE_CUES, _NS) or _has_cue(g, _GLUCOSE_VARIABILITY_CUES, _NS)) and _has_cue(f, _FITNESS_LOW_CUES, _NS):
                connections.append(
                    "- **glucose + fitness** — Elevated/variable glucose alongside low activity. "
                    "Active days may show better glucose control — compare dates."
                )
            elif _has_cue(g, _GLUCOSE_IMPROVED_CUES, _NS) and _has_cue(f, _FITNESS_ACTIVE_CUES, _NS):
                connections.append(
                    "- **glucose + fitness** — Improved glucose readings align with activity data. "
                    "Compare active days with glucose trends to check the correlation."
                )

        # Rule 3: glucose variability + poor sleep
        if "glucose" in by_domain and "sleep" in by_domain:
            if _has_cue(by_domain["glucose"], _GLUCOSE_VARIABILITY_CUES, _NS) and _has_cue(by_domain["sleep"], _SLEEP_POOR_CUES, _NS):
                connections.append(
                    "- **glucose + sleep** — Glucose variability alongside poor sleep data. "
                    "Sleep quality affects insulin sensitivity — compare dates."
                )

        # Rule 4: high calories + low activity
        if "nutrition" in by_domain and "fitness" in by_domain:
            if _has_cue(by_domain["nutrition"], _HIGH_CAL_CUES, _NS) and _has_cue(by_domain["fitness"], _FITNESS_LOW_CUES, _NS):
                connections.append(
                    "- **nutrition + fitness** — High calorie intake alongside low activity. "
                    "This combination may explain trends in other metrics."
                )

        return "\n".join(connections)

    @staticmethod
    def _build_responder_messages(
        *,
        base_messages: list[dict[str, Any]],
        response_prompt: str,
        combined_data: str,
        reflection: Any = None,
        findings: list | None = None,
        user_role: str = "patient",
        failed_domains: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Build messages for the responder model."""
        from lib.ai_foundation.agents.health_query.evidence import (
            build_summary_from_findings,
            format_coverage_note,
            format_patient,
            format_provider,
        )

        messages: list[dict[str, Any]] = []

        # Keep system messages from base (system prompt, context)
        for msg in base_messages:
            if msg.get("role") == "system" and msg.get("_meta", {}).get("type") != "instruction":
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

        # Note failed domains so the LLM acknowledges the gap
        if failed_domains:
            domain_list = ", ".join(failed_domains)
            messages.append({
                "role": "system",
                "content": (
                    f"DATA GAP: The following domains could not be retrieved due to a "
                    f"system error: {domain_list}. Briefly acknowledge this gap in your "
                    f"response so the user knows this data was not available."
                ),
                "_meta": {"type": "data_gap"},
            })

        # Inject evidence summary from specialist findings
        if findings:
            summary = build_summary_from_findings(findings)
            evidence_text = format_provider(summary) if user_role in ("care_provider", "research") else format_patient(summary)
            coverage_note = format_coverage_note(summary)
            if coverage_note:
                evidence_text = f"{evidence_text}\n{coverage_note}" if evidence_text else coverage_note
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
