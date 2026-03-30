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
import inspect
import logging
import time
from dataclasses import dataclass
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

from lib.ai_foundation.models.gateway import safe_cost

from .contracts import QueryIntent, QueryResponse, resolve_specialist_domains
from .coordinator import Coordinator
from .reasoning_engine import ReasoningEngine, ReasoningTier

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class _PipelineContext:
    pipeline_start: float
    user_timestamp: datetime
    trace_id: str
    ctx: Any  # AgentContext
    intent: Any  # QueryIntent
    meta: Any  # LLMResponse metadata


async def _maybe_await(result: Any) -> None:
    """Await values only when a dependency returns an awaitable.

    Gateway observability hooks are sync in production but often AsyncMock'd in tests.
    """
    if inspect.isawaitable(result):
        await result


def _sse_event_name(event: str) -> str:
    """Extract SSE event name from a formatted event payload."""
    first_line = event.split("\n", 1)[0].strip()
    if not first_line.startswith("event:"):
        return ""
    return first_line.split(":", 1)[1].strip()


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
        self._prompt_cache: dict[str, str] = {}

    # ── Public: Non-streaming ─────────────────────────────────────────────

    async def run(self, input: AgentInput) -> AgentOutput:
        trace_id = f"trc_{uuid4().hex[:16]}"

        try:
            pc = await self._init_pipeline(input)
            pipeline_start = pc.pipeline_start
            user_timestamp = pc.user_timestamp
            trace_id = pc.trace_id
            ctx = pc.ctx
            intent = pc.intent
            meta = pc.meta

            # ── Memory commands (remember/forget/list) ──
            if intent.memory_action:
                output = await self._handle_memory_action(input, intent, ctx, trace_id)
                await _maybe_await(self.gateway.langfuse_trace_output(trace_id=trace_id, output_text=output.message))
                await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                self._schedule_background(input)
                return output

            if not intent.is_ready:
                output = self._build_clarification(intent, meta)
                await _maybe_await(self.gateway.langfuse_trace_output(trace_id=trace_id, output_text=output.message))
                await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                self._schedule_background(input)
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
                    user_role=input.context.user_role,
                    trace_id=trace_id,
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
                    user_role=input.context.user_role,
                )

            elapsed = int((time.perf_counter() - pipeline_start) * 1000)
            total_cost = safe_cost(meta) + result.total_cost

            output = AgentOutput(
                message=result.response, is_ready=True,
                suggestions=[s.model_dump() for s in intent.suggestions],
                data={
                    "data_types": [dt.value for dt in intent.data_types],
                    "intent_confidence": intent.confidence,
                    "coverage_confidence": result.coverage_confidence,
                    "reflection_confidence": result.reflection_confidence,
                    "data_gaps": result.data_gaps,
                    "data_conflicts": result.data_conflicts,
                    "rounds_used": result.rounds_used,
                    "tools_called": result.tools_called,
                    "tier": result.tier,
                },
                trace_id=trace_id,
                cost_usd=total_cost,
                latency_ms=elapsed,
                model_id=result.responder_model,
            )

            await _maybe_await(self.gateway.langfuse_trace_output(trace_id=trace_id, output_text=output.message))

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
        trace_id = f"trc_{uuid4().hex[:16]}"

        try:
            yield sse_status(PipelineStage.EXTRACTING_INTENT, "Understanding the question...")
            pc = await self._init_pipeline(input)
            pipeline_start = pc.pipeline_start
            user_timestamp = pc.user_timestamp
            trace_id = pc.trace_id
            ctx = pc.ctx
            intent = pc.intent
            meta = pc.meta
            yield sse_intent(intent.model_dump(mode="json", exclude_none=True))

            # ── Memory commands (remember/forget/list) ──
            if intent.memory_action:
                output = await self._handle_memory_action(input, intent, ctx, trace_id)
                await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                self._schedule_background(input)
                yield sse_token(output.message)
                yield sse_done(SSEDonePayload(trace_id=trace_id, latency_ms=int((time.perf_counter() - pipeline_start) * 1000)))
                return

            if not intent.is_ready:
                msg = intent.clarification_msg or "Could you tell me more?"
                output = AgentOutput(message=msg, is_ready=False, trace_id=trace_id)
                await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                self._schedule_background(input)
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
                    user_role=input.context.user_role,
                    trace_id=trace_id,
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
                    user_role=input.context.user_role,
                )

            async with asyncio.timeout(settings.STREAMING_PIPELINE_TIMEOUT_SECONDS):
                async for event in event_source:
                    event_name = _sse_event_name(event)

                    # Intercept done event to save turn and inject suggestions
                    if event_name == "done":
                        # Extract full_response + metadata from the done payload
                        full_text = ""
                        done_data: dict = {}
                        try:
                            import json as _json
                            data_line = event.split("data: ", 1)[1].split("\n")[0]
                            done_data = _json.loads(data_line)
                            full_text = done_data.get("data", {}).get("full_response", "")
                        except (IndexError, ValueError, KeyError):
                            pass

                        engine_data = done_data.get("data", {})
                        intent_cost = safe_cost(meta)
                        engine_cost = done_data.get("cost_usd")
                        total_cost = (engine_cost or 0.0) + intent_cost
                        elapsed = int((time.perf_counter() - pipeline_start) * 1000)

                        output = AgentOutput(
                            message=full_text, is_ready=True,
                            trace_id=trace_id,
                            cost_usd=total_cost,
                            latency_ms=elapsed,
                            model_id=done_data.get("model_id"),
                            data={
                                "data_types": [dt.value for dt in intent.data_types],
                                "intent_confidence": intent.confidence,
                                "coverage_confidence": engine_data.get("coverage_confidence"),
                                "reflection_confidence": engine_data.get("reflection_confidence"),
                                "data_gaps": engine_data.get("data_gaps"),
                                "data_conflicts": engine_data.get("data_conflicts"),
                                "rounds_used": engine_data.get("rounds_used"),
                                "tools_called": engine_data.get("tools_called"),
                                "tier": engine_data.get("tier"),
                            },
                        )
                        if full_text:
                            await _maybe_await(self.gateway.langfuse_trace_output(trace_id=trace_id, output_text=full_text))
                        await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                        self._schedule_background(input)

                        # Emit our own done event with suggestions and trace
                        yield sse_done(SSEDonePayload(
                            suggestions=[s.model_dump() for s in intent.suggestions],
                            trace_id=trace_id,
                            cost_usd=total_cost,
                            latency_ms=elapsed,
                            model_id=done_data.get("model_id"),
                            data=engine_data,
                        ))
                        continue

                    yield event

        except TimeoutError:
            elapsed = int((time.perf_counter() - pipeline_start) * 1000)
            logger.error("Streaming pipeline timed out after %dms (limit=%ds)",
                         elapsed, settings.STREAMING_PIPELINE_TIMEOUT_SECONDS)
            yield sse_error(
                message="This query is taking longer than expected. Please try a simpler question or try again.",
                code="pipeline_timeout",
            )
        except Exception as exc:
            logger.exception("HealthQueryAgent.run_stream failed: %s", exc)
            yield sse_error(message="I'm having trouble right now.", code="agent_error",
                            fallback_text="Please try again in a moment.")

    # ── Pipeline steps ────────────────────────────────────────────────────

    async def _init_pipeline(self, input: AgentInput) -> _PipelineContext:
        """Shared setup for run() and run_stream(): timing, tracing, context, intent."""
        pipeline_start = time.perf_counter()
        user_timestamp = datetime.now(timezone.utc)
        trace_id = f"trc_{uuid4().hex[:16]}"

        await _maybe_await(self.gateway.set_langfuse_context(
            session_id=input.context.thread_id,
            user_id=input.context.user_id,
        ))
        await _maybe_await(self.gateway.langfuse_trace_input(
            trace_id=trace_id,
            name="health_query",
            input_text=input.message,
            metadata={"user_role": input.context.user_role, "patient_ids": input.context.patient_ids},
        ))

        ctx = await self._load_context(input)
        ctx.local_time = (input.context.metadata or {}).get("local_time")
        intent, meta = await self._extract_intent(input, ctx)

        return _PipelineContext(
            pipeline_start=pipeline_start,
            user_timestamp=user_timestamp,
            trace_id=trace_id,
            ctx=ctx,
            intent=intent,
            meta=meta,
        )

    async def _load_context(self, input: AgentInput) -> Any:
        if not self.context_loader:
            from lib.ai_foundation.agents.core.context_loader import AgentContext as Ctx
            return Ctx()
        return await self.context_loader.load(
            patient_id=input.context.patient_id,
            patient_ids=input.context.patient_ids,
            thread_id=input.context.thread_id,
        )

    async def _extract_intent(self, input: AgentInput, ctx: Any) -> tuple[QueryIntent, Any]:
        self._ensure_prompts()
        system_prompt = self._get_system_prompt(input.context.user_role)
        intent_prompt = self._render("hq_intent_extraction")

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": intent_prompt},
        ]

        # Inject device local time for accurate date resolution
        local_time = (input.context.metadata or {}).get("local_time")
        if local_time:
            messages.append({"role": "system", "content": (
                f"User's local time: {local_time}. "
                f"Use THIS for resolving 'today', 'yesterday', 'this week', etc."
            )})

        if ctx.thread_summary:
            messages.append({"role": "system", "content": f"Conversation summary:\n{ctx.thread_summary}"})

        if input.context.user_role in ("care_provider", "research") and ctx.patient_names:
            names = list(ctx.patient_names.values())
            messages.append({"role": "system", "content": (
                f"The user is a {input.context.user_role} asking about: {', '.join(names)}. "
                f"In suggestions, use patient names, NEVER use 'my' or 'your'."
            )})

        if ctx.facts:
            by_cat: dict[str, list[str]] = {}
            for f in ctx.facts[:settings.MAX_CONTEXT_FACTS]:
                cat = f.get("category", "other")
                by_cat.setdefault(cat, []).append(f"{f['key']}: {f['value']}")
            lines = ["Patient memories:"]
            for cat, items in by_cat.items():
                lines.append(f"  {cat.title()}: {', '.join(items)}")
            messages.append({"role": "system", "content": "\n".join(lines)})

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
                "tier": (output.data or {}).get("tier"),
                "rounds_used": (output.data or {}).get("rounds_used"),
                "tools_called": (output.data or {}).get("tools_called"),
                "cost_usd": output.cost_usd,
                "latency_ms": output.latency_ms,
                "model_id": output.model_id,
            },
        )

    async def _handle_memory_action(
        self, input: AgentInput, intent: QueryIntent, ctx: Any, trace_id: str,
    ) -> AgentOutput:
        """Handle memory commands: add, delete, list."""
        from lib.ai_foundation.memory.base import MemoryFact, MemorySource
        from lib.ai_foundation.agents.core.fact_extractor import CANONICAL_MEMORY_KEYS, normalize_memory_key

        pid = self._resolve_single_pid(input)
        if not pid or not self.memory:
            return AgentOutput(message="I can't manage memories without knowing which patient.", is_ready=True, trace_id=trace_id)

        action = intent.memory_action

        if action == "add":
            if not (intent.memory_key and intent.memory_value):
                return AgentOutput(
                    message="I'd like to remember that for you, but I'm not sure what to save. Could you say something like \"remember that I'm vegetarian\"?",
                    is_ready=True, trace_id=trace_id,
                )
            key = normalize_memory_key(intent.memory_key)
            meta = CANONICAL_MEMORY_KEYS.get(key, {"category": "other", "permanent": False})
            fact = MemoryFact(
                key=key,
                value=intent.memory_value.strip(),
                category=meta["category"],
                source=MemorySource.USER_EXPLICIT.value,
                agent_id=self.agent_id,
                confidence=1.0,
                is_permanent=meta["permanent"],
            )
            await self.memory.upsert_patient_facts(pid, [fact])
            return AgentOutput(
                message=f"Got it! I'll remember that: **{key.replace('_', ' ')}** = {intent.memory_value}.",
                is_ready=True, trace_id=trace_id,
            )

        elif action == "delete":
            if not intent.memory_key:
                return AgentOutput(
                    message="What would you like me to forget? Try \"forget my weight\" or \"forget my dietary preference\".",
                    is_ready=True, trace_id=trace_id,
                )
            key = normalize_memory_key(intent.memory_key)
            deleted = await self.memory.delete_patient_fact(pid, key)
            if deleted:
                return AgentOutput(message=f"Done — I've forgotten your **{key.replace('_', ' ')}**.", is_ready=True, trace_id=trace_id)
            return AgentOutput(message=f"I don't have a memory for \"{key.replace('_', ' ')}\".", is_ready=True, trace_id=trace_id)

        elif action == "list":
            facts = await self.memory.get_patient_facts(pid)
            if not facts:
                return AgentOutput(message="I don't have any memories about you yet. As we chat, I'll learn your preferences and goals!", is_ready=True, trace_id=trace_id)

            by_cat: dict[str, list[str]] = {}
            for f in facts:
                cat = getattr(f, "category", "other") or "other"
                by_cat.setdefault(cat, []).append(f"**{f.key.replace('_', ' ')}**: {f.value}")
            lines = ["Here's what I remember about you:\n"]
            for cat, items in by_cat.items():
                lines.append(f"**{cat.title()}**")
                for item in items:
                    lines.append(f"- {item}")
                lines.append("")
            lines.append("You can say \"forget [topic]\" to remove any of these.")
            return AgentOutput(message="\n".join(lines), is_ready=True, trace_id=trace_id)

        # Unknown action fallback
        return AgentOutput(message="I'm not sure what you'd like me to remember. Could you try again?", is_ready=True, trace_id=trace_id)

    def _schedule_background(self, input: AgentInput) -> None:
        """Schedule background tasks with timeout and error handling."""
        thread_id = input.context.thread_id or ""
        if self.persistence:
            asyncio.create_task(self._run_background(
                self.persistence.compact_if_needed(
                    thread_id=input.context.thread_id, agent_id=self.agent_id,
                    patient_ids=input.context.patient_ids,
                ),
                name="compaction", thread_id=thread_id,
            ))
        if self.fact_extractor:
            pid = self._resolve_single_pid(input)
            if pid:
                asyncio.create_task(self._run_background(
                    self.fact_extractor.extract_if_needed(
                        message=input.message, patient_id=pid, agent_id=self.agent_id,
                    ),
                    name="fact_extraction", thread_id=thread_id,
                ))

    async def _run_background(self, coro: Any, *, name: str, thread_id: str) -> None:
        """Run a background coroutine with timeout and error handling."""
        try:
            await asyncio.wait_for(coro, timeout=settings.BACKGROUND_TASK_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("Background task %s timed out (thread=%s)", name, thread_id)
        except asyncio.CancelledError:
            raise  # never swallow cancellation
        except Exception as exc:
            logger.warning("Background task %s failed (thread=%s): %s", name, thread_id, exc)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _ensure_prompts(self) -> None:
        if self._prompts_registered or not self.prompts:
            return
        if "hq_system_patient" not in self.prompts:
            self.prompts.register_directory(_PROMPTS_DIR, namespace="health_query")
        self._prompts_registered = True

    def _render(self, template_name: str, **extra_vars: str) -> str:
        """Render a prompt with common variables (available_data_types, current_time)."""
        from lib.ai_foundation.agents.health_query.contracts import AVAILABLE_HEALTH_DOMAINS
        template = self.prompts.get(template_name)
        return template.render(
            available_data_types=AVAILABLE_HEALTH_DOMAINS,
            current_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            **extra_vars,
        )

    def _get_system_prompt(self, user_role: str) -> str:
        """Get system prompt, cached per role per minute."""
        self._ensure_prompts()
        now_minute = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        cache_key = f"{user_role}:{now_minute}"
        if cache_key in self._prompt_cache:
            return self._prompt_cache[cache_key]

        name_map = {"research": "hq_system_research", "admin": "hq_system_research", "care_provider": "hq_system_care_provider", "patient": "hq_system_patient"}
        rendered = self._render(name_map.get(user_role, "hq_system_patient"))

        if len(self._prompt_cache) > settings.PROMPT_CACHE_MAX_SIZE:
            self._prompt_cache.clear()
        self._prompt_cache[cache_key] = rendered
        return rendered

    def _get_reasoning_prompts(self) -> tuple[str, str]:
        """Return (reasoning_prompt, response_prompt) for the engine."""
        self._ensure_prompts()
        reasoning = self._render("hq_reasoning")
        response = self._render("hq_final_response")
        return reasoning, response

    def _build_clarification(self, intent: QueryIntent, meta: Any) -> AgentOutput:
        return AgentOutput(
            message=intent.clarification_msg or "Could you tell me more?",
            is_ready=False,
            suggestions=[s.model_dump() for s in intent.suggestions],
            data={"data_types": [dt.value for dt in intent.data_types], "confidence": intent.confidence},
            trace_id=meta.trace_id if meta else None,
            cost_usd=safe_cost(meta) or None,
            model_id=meta.model_id if meta else None,
        )

    @staticmethod
    def _resolve_patient_ids(input: AgentInput) -> list[str]:
        return input.context.patient_ids or (
            [input.context.patient_id] if input.context.patient_id else []
        )

    @staticmethod
    def _resolve_single_pid(input: AgentInput) -> str | None:
        """Resolve a single patient ID from input context."""
        pid = input.context.patient_id
        if not pid and input.context.patient_ids and len(input.context.patient_ids) == 1:
            pid = input.context.patient_ids[0]
        return pid

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
            data_types=output.data.get("data_types"),
            confidence=output.data.get("intent_confidence") or output.data.get("confidence"),
            coverage_confidence=output.data.get("coverage_confidence"),
            reflection_confidence=output.data.get("reflection_confidence"),
            data_gaps=output.data.get("data_gaps"),
            data_conflicts=output.data.get("data_conflicts"),
            final_response=output.message if output.is_ready else None,
            clarification_msg=output.message if not output.is_ready else None,
            suggestions=output.suggestions, trace_id=output.trace_id,
            cost_usd=output.cost_usd, latency_ms=output.latency_ms,
        )
