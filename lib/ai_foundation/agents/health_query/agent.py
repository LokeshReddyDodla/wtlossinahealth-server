"""
Health Query Agent — thin orchestrator powered by agentic reasoning.

The agent coordinates:
  1. ContextLoader → loads facts, history, summary, names
  2. Gateway.extract → intent extraction (is_ready check + suggestions)
  3. ReasoningEngine → agentic tool-calling loop (thinker → tools → responder)
  4. PersistenceService → saves turns (blocking), compacts (background)
  5. FactExtractor → extracts facts (background)
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

from lib.ai_foundation.agents.base import BaseAgent
from lib.ai_foundation.agents.state import AgentInput, AgentOutput
from lib.ai_foundation.config import settings
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.streaming.sse import (
    PipelineStage,
    SSEDonePayload,
    sse_done,
    sse_error,
    sse_intent,
    sse_status,
    sse_token,
)

from .contracts import QueryIntent, QueryResponse, resolve_specialist_domains
from .coordinator import Coordinator
from .reasoning_engine import ReasoningEngine, ReasoningTier

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


class HealthQueryAgent(BaseAgent):
    """Foundation-native health query agent — thin orchestrator with agentic reasoning."""

    agent_id = "health_query_v3"

    def __init__(
        self,
        *,
        context_loader: Any = None,
        reasoning_engine: ReasoningEngine | None = None,
        coordinator: Coordinator | None = None,
        persistence: Any = None,
        fact_extractor: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.context_loader = context_loader
        self.reasoning_engine = reasoning_engine
        self.coordinator = coordinator
        self.persistence = persistence
        self.fact_extractor = fact_extractor
        self._prompts_registered = False

    # ── Public: Non-streaming ─────────────────────────────────────────────

    async def run(self, input: AgentInput) -> AgentOutput:
        pipeline_start = time.perf_counter()
        user_timestamp = datetime.now(timezone.utc)
        trace_id = f"trc_{uuid4().hex[:16]}"

        try:
            # Set Langfuse context for this request
            self.gateway.set_langfuse_context(
                session_id=input.context.thread_id,
                user_id=input.context.user_id,
            )

            # Set trace-level input
            self.gateway.langfuse_trace_input(
                trace_id=trace_id,
                input_text=input.message,
                metadata={"user_role": input.context.user_role, "patient_ids": input.context.patient_ids},
            )

            ctx = await self._load_context(input)
            intent, meta = await self._extract_intent(input, ctx)

            if not intent.is_ready:
                output = self._build_clarification(intent, meta)
                self.gateway.langfuse_trace_output(trace_id=trace_id, output_text=output.message)
                await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                return output

            # ── Route: single-agent vs multi-agent ──
            patient_ids = self._resolve_patient_ids(input)
            system_prompt = self._get_system_prompt(input.context.user_role)
            reasoning_prompt, response_prompt = self._get_reasoning_prompts()
            tier = self._resolve_tier(input)
            specialist_domains = resolve_specialist_domains(intent.data_types)


            if self.coordinator and len(specialist_domains) > 1 and tier != ReasoningTier.BASIC:
                # Multi-agent path
                result = await self.coordinator.orchestrate(
                    user_message=input.message,
                    system_prompt=system_prompt,
                    reasoning_prompt=reasoning_prompt,
                    response_prompt=response_prompt,
                    context=ctx,
                    patient_ids=patient_ids,
                    domains=specialist_domains,
                    tier=tier,
                    patient_names=ctx.patient_names,
                )
            else:
                # Single-agent path
                result = await self.reasoning_engine.reason(
                    user_message=input.message,
                    system_prompt=system_prompt,
                    reasoning_prompt=reasoning_prompt,
                    response_prompt=response_prompt,
                    context=ctx,
                    patient_ids=patient_ids,
                    tier=tier,
                    intent_data_types=[dt.value for dt in intent.data_types],
                    patient_names=ctx.patient_names,
                )

            elapsed = int((time.perf_counter() - pipeline_start) * 1000)
            total_cost = (meta.usage.cost.total_cost if meta else 0) + result.total_cost

            output = AgentOutput(
                message=result.response, is_ready=True,
                suggestions=[s.model_dump() for s in intent.suggestions],
                data={
                    "data_types": [dt.value for dt in intent.data_types],
                    "confidence": intent.confidence,
                    "rounds_used": result.rounds_used,
                    "tools_called": result.tools_called,
                    "tier": result.tier,
                },
                trace_id=trace_id,
                cost_usd=total_cost,
                latency_ms=elapsed,
                model_id=result.responder_model,
            )

            self.gateway.langfuse_trace_output(trace_id=trace_id, output_text=output.message)

            await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
            self._schedule_background(input)
            return output

        except Exception as exc:
            logger.exception("HealthQueryAgent.run failed: %s", exc)
            return AgentOutput(
                message="I'm having trouble processing your request right now. Please try again.",
                is_ready=False, trace_id=trace_id,
            )

    # ── Public: SSE Streaming ─────────────────────────────────────────────

    async def run_stream(self, input: AgentInput) -> AsyncIterator[str]:
        pipeline_start = time.perf_counter()
        user_timestamp = datetime.now(timezone.utc)
        trace_id = f"trc_{uuid4().hex[:16]}"

        try:
            # Set Langfuse context for this request
            self.gateway.set_langfuse_context(
                session_id=input.context.thread_id,
                user_id=input.context.user_id,
            )

            # Set trace-level input
            self.gateway.langfuse_trace_input(
                trace_id=trace_id,
                input_text=input.message,
                metadata={"user_role": input.context.user_role, "patient_ids": input.context.patient_ids},
            )

            yield sse_status(PipelineStage.EXTRACTING_INTENT, "Understanding the question...")
            ctx = await self._load_context(input)
            intent, meta = await self._extract_intent(input, ctx)
            yield sse_intent(intent.model_dump(mode="json", exclude_none=True))

            if not intent.is_ready:
                msg = intent.clarification_msg or "Could you tell me more?"
                output = AgentOutput(message=msg, is_ready=False, trace_id=trace_id)
                await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                yield sse_token(msg)
                yield sse_done(SSEDonePayload(
                    suggestions=[s.model_dump() for s in intent.suggestions],
                    trace_id=trace_id,
                    latency_ms=int((time.perf_counter() - pipeline_start) * 1000),
                ))
                return

            # ── Route: single-agent vs multi-agent (streaming) ──
            patient_ids = self._resolve_patient_ids(input)
            system_prompt = self._get_system_prompt(input.context.user_role)
            reasoning_prompt, response_prompt = self._get_reasoning_prompts()
            tier = self._resolve_tier(input)
            specialist_domains = resolve_specialist_domains(intent.data_types)


            if self.coordinator and len(specialist_domains) > 1 and tier != ReasoningTier.BASIC:
                event_source = self.coordinator.orchestrate_stream(
                    user_message=input.message,
                    system_prompt=system_prompt,
                    reasoning_prompt=reasoning_prompt,
                    response_prompt=response_prompt,
                    context=ctx,
                    patient_ids=patient_ids,
                    domains=specialist_domains,
                    tier=tier,
                    patient_names=ctx.patient_names,
                )
            else:
                event_source = self.reasoning_engine.reason_stream(
                    user_message=input.message,
                    system_prompt=system_prompt,
                    reasoning_prompt=reasoning_prompt,
                    response_prompt=response_prompt,
                    context=ctx,
                    patient_ids=patient_ids,
                    tier=tier,
                    intent_data_types=[dt.value for dt in intent.data_types],
                    patient_names=ctx.patient_names,
                )

            async for event in event_source:
                # Intercept done event to save turn and inject suggestions
                if 'event: done' in event:
                    # Extract full_response from the done payload
                    full_text = ""
                    try:
                        import json as _json
                        data_line = event.split("data: ", 1)[1].split("\n")[0]
                        done_data = _json.loads(data_line)
                        full_text = done_data.get("data", {}).get("full_response", "")
                    except (IndexError, ValueError, KeyError):
                        pass

                    output = AgentOutput(
                        message=full_text, is_ready=True,
                        trace_id=trace_id,
                    )
                    if full_text:
                        self.gateway.langfuse_trace_output(trace_id=trace_id, output_text=full_text)
                    await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                    self._schedule_background(input)

                    # Emit our own done event with suggestions and trace
                    elapsed = int((time.perf_counter() - pipeline_start) * 1000)
                    yield sse_done(SSEDonePayload(
                        suggestions=[s.model_dump() for s in intent.suggestions],
                        trace_id=trace_id,
                        latency_ms=elapsed,
                    ))
                    continue

                yield event

        except Exception as exc:
            logger.exception("HealthQueryAgent.run_stream failed: %s", exc)
            yield sse_error(message="I'm having trouble right now.", code="agent_error",
                            fallback_text="Please try again in a moment.")

    # ── Pipeline steps ────────────────────────────────────────────────────

    async def _load_context(self, input: AgentInput) -> Any:
        if not self.context_loader:
            from .context_loader import AgentContext as Ctx
            return Ctx()
        return await self.context_loader.load(
            patient_id=input.context.patient_id,
            patient_ids=input.context.patient_ids,
            thread_id=input.context.thread_id,
        )

    async def _extract_intent(self, input: AgentInput, ctx: Any) -> tuple[QueryIntent, Any]:
        self._ensure_prompts()
        system_prompt = self._get_system_prompt(input.context.user_role)
        intent_prompt = self.prompts.get("hq_intent_extraction").body

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": intent_prompt},
        ]

        if ctx.thread_summary:
            messages.append({"role": "system", "content": f"Conversation summary:\n{ctx.thread_summary}"})

        if input.context.user_role in ("care_provider", "admin") and ctx.patient_names:
            names = list(ctx.patient_names.values())
            messages.append({"role": "system", "content": (
                f"The user is a {input.context.user_role} asking about: {', '.join(names)}. "
                f"In suggestions, use patient names, NEVER use 'my' or 'your'."
            )})

        if ctx.facts:
            lines = [f"- {f['key']}: {f['value']}" for f in ctx.facts[:settings.MAX_CONTEXT_FACTS]]
            messages.append({"role": "system", "content": "Patient facts:\n" + "\n".join(lines)})

        messages.extend(ctx.history[-settings.MAX_HISTORY_MESSAGES:])
        messages.append({"role": "user", "content": input.message})

        intent, meta = await self.gateway.extract(
            messages=messages, response_model=QueryIntent, task=ModelTask.INTENT_EXTRACTION,
        )

        return intent, meta

    # ── Persistence + background ──────────────────────────────────────────

    async def _save_turn(
        self, input: AgentInput, output: AgentOutput, intent: QueryIntent,
        user_timestamp: Any = None,
    ) -> None:
        if not self.persistence:
            return
        await self.persistence.save_turn(
            thread_id=input.context.thread_id,
            user_message=input.message,
            assistant_message=output.message,
            agent_id=self.agent_id,
            patient_ids=input.context.patient_ids,
            user_timestamp=user_timestamp,
            intent_metadata={
                "is_ready": output.is_ready,
                "data_types": [dt.value for dt in intent.data_types],
                "confidence": intent.confidence,
                "trace_id": output.trace_id,
            },
        )

    def _schedule_background(self, input: AgentInput) -> None:
        """Fire-and-forget background tasks."""
        if self.persistence:
            asyncio.ensure_future(self.persistence.compact_if_needed(
                thread_id=input.context.thread_id, agent_id=self.agent_id,
                patient_ids=input.context.patient_ids,
            ))
        if self.fact_extractor:
            pid = input.context.patient_id
            if not pid and input.context.patient_ids and len(input.context.patient_ids) == 1:
                pid = input.context.patient_ids[0]
            if pid:
                asyncio.ensure_future(self.fact_extractor.extract_if_needed(
                    message=input.message, patient_id=pid, agent_id=self.agent_id,
                ))

    # ── Helpers ───────────────────────────────────────────────────────────

    def _ensure_prompts(self) -> None:
        if self._prompts_registered or not self.prompts:
            return
        if "hq_system_patient" not in self.prompts:
            self.prompts.register_directory(_PROMPTS_DIR, namespace="health_query")
        self._prompts_registered = True

    _prompt_cache: dict[str, tuple[str, str]] = {}

    def _get_system_prompt(self, user_role: str) -> str:
        """Get system prompt, cached per role per minute."""
        now_minute = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        cache_key = f"{user_role}:{now_minute}"
        if cache_key in self._prompt_cache:
            return self._prompt_cache[cache_key]

        name_map = {"admin": "hq_system_admin", "care_provider": "hq_system_care_provider", "patient": "hq_system_patient"}
        template = self.prompts.get(name_map.get(user_role, "hq_system_patient"))
        rendered = template.render(current_time=f"{now_minute} UTC")

        if len(self._prompt_cache) > settings.PROMPT_CACHE_MAX_SIZE:
            self._prompt_cache.clear()
        self._prompt_cache[cache_key] = rendered
        return rendered

    def _get_reasoning_prompts(self) -> tuple[str, str]:
        """Return (reasoning_prompt, response_prompt) for the engine."""
        self._ensure_prompts()
        reasoning = self.prompts.get("hq_reasoning").body
        response = self.prompts.get("hq_final_response").body
        return reasoning, response

    def _build_clarification(self, intent: QueryIntent, meta: Any) -> AgentOutput:
        return AgentOutput(
            message=intent.clarification_msg or "Could you tell me more?",
            is_ready=False,
            suggestions=[s.model_dump() for s in intent.suggestions],
            data={"data_types": [dt.value for dt in intent.data_types], "confidence": intent.confidence},
            trace_id=meta.trace_id if meta else None,
            cost_usd=meta.usage.cost.total_cost if meta else None,
            model_id=meta.model_id if meta else None,
        )

    @staticmethod
    def _resolve_patient_ids(input: AgentInput) -> list[str]:
        return input.context.patient_ids or (
            [input.context.patient_id] if input.context.patient_id else []
        )

    @staticmethod
    def _resolve_tier(input: AgentInput) -> ReasoningTier:
        """Resolve reasoning tier from input context or default."""
        tier_str = (input.context.metadata or {}).get("tier", settings.REASONING_DEFAULT_TIER)
        try:
            return ReasoningTier(tier_str)
        except ValueError:
            return ReasoningTier.STANDARD

    def to_query_response(self, input: AgentInput, output: AgentOutput) -> QueryResponse:
        return QueryResponse(
            is_ready=output.is_ready, user_message=input.message, message=output.message,
            data_types=output.data.get("data_types"), confidence=output.data.get("confidence"),
            final_response=output.message if output.is_ready else None,
            clarification_msg=output.message if not output.is_ready else None,
            suggestions=output.suggestions, trace_id=output.trace_id,
            cost_usd=output.cost_usd, latency_ms=output.latency_ms,
        )
