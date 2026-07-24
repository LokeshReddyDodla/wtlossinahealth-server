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
from lib.ai_foundation.agents.state import AgentContext, AgentInput, AgentOutput
from lib.ai_foundation.config import settings
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.agents.core.bubbles import extract_await, split_bubbles, strip_bubbles
from lib.core.types import NUMBER_FIDELITY_INSTRUCTION, RESPECTFUL_REGISTER_INSTRUCTION, ai_language_name, DEFAULT_AI_LANGUAGE
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

from .contracts import ProactiveNarration, QueryIntent, QueryResponse, expand_to_domain_types, resolve_specialist_domains
from .coordinator import Coordinator
from .reasoning_engine import ReasoningEngine, ReasoningTier

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Canned fallback when the extractor marks not-ready without a clarification.
_CLARIFY_FALLBACK = "Could you tell me more?"


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
        translator: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.context_loader = context_loader
        self.reasoning_engine = reasoning_engine
        self.coordinator = coordinator
        self.persistence = persistence
        self.fact_extractor = fact_extractor
        self.translator = translator
        self._prompts_registered = False
        self._prompt_cache: dict[str, str] = {}
        # Strong refs: the event loop only weak-refs tasks, so a GC pass can
        # destroy an unfinished fire-and-forget task (fact extraction /
        # compaction / audit copy silently never happening).
        self._bg_tasks: set[asyncio.Task] = set()

    def _spawn_background(self, coro: Any, *, name: str, thread_id: str) -> None:
        task = asyncio.create_task(
            self._run_background(coro, name=name, thread_id=thread_id)
        )
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    # ── Public: Non-streaming ─────────────────────────────────────────────

    async def run(self, input: AgentInput, _is_retry: bool = False) -> AgentOutput:
        # Fallbacks in case _init_pipeline fails before assigning the real ones
        # (the exception handlers below reference both).
        trace_id = f"trc_{uuid4().hex[:16]}"
        pipeline_start = time.perf_counter()
        ctx = None  # bound after _init_pipeline; error paths localize best-effort

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
                output.message = await self._localize_text(output.message, ctx, input=input, cached=False)
                await _maybe_await(self.gateway.langfuse_trace_output(trace_id=trace_id, output_text=output.message))
                turn_id = await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                self._schedule_background(input, ctx, output, turn_id)
                return output

            if not intent.is_ready:
                output = self._build_clarification(intent, meta)
                # A not-yet-logged ask lands here (is_ready=False), so the
                # await arms in the clarify branch, not only the execution one.
                if intent.awaits_log:
                    await self._register_pending_request(
                        input, intent.awaits_log, output.suggestions,
                        self._effective_language(input, ctx),
                    )
                if not intent.clarification_msg:  # canned fallback needs localizing
                    output.message = await self._localize_text(output.message, ctx, input=input)
                await _maybe_await(self.gateway.langfuse_trace_output(trace_id=trace_id, output_text=output.message))
                turn_id = await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                self._schedule_background(input, ctx, output, turn_id)
                return output

            # ── Route: single-agent vs multi-agent ──
            patient_ids = self._resolve_patient_ids(input)
            system_prompt = self._get_system_prompt(input.context.user_role)
            response_language = self._effective_language(input, ctx)
            reasoning_prompt, response_prompt = self._get_reasoning_prompts(input, response_language)
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
                    # Expand to the full domain family so a glucose query
                    # about spikes/lows fetches the event records, not just
                    # summaries (the single-agent path otherwise trusts the
                    # extractor's narrow pick — see expand_to_domain_types).
                    intent_data_types=[dt.value for dt in expand_to_domain_types(intent.data_types)],
                    patient_names=ctx.patient_names,
                    user_role=input.context.user_role,
                    trace_id=trace_id,
                )

            elapsed = int((time.perf_counter() - pipeline_start) * 1000)
            total_cost = safe_cost(meta) + result.total_cost

            clean_response, awaited = extract_await(result.response)
            # Reasoning responders routinely drop the inline [[AWAIT]] marker;
            # the query-side signal from intent extraction is the deterministic
            # fallback so the continuation loop still arms.
            awaited = awaited or intent.awaits_log
            suggestions = [s.model_dump(exclude_none=True) for s in intent.suggestions]
            if awaited:
                await self._register_pending_request(input, awaited, suggestions, response_language)
            bubbles = split_bubbles(clean_response)
            output = AgentOutput(
                message=strip_bubbles(clean_response), is_ready=True,
                suggestions=suggestions,
                data={
                    "messages": bubbles,
                    "pending_request": awaited,
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

            await _maybe_await(self.gateway.langfuse_trace_output(
                trace_id=trace_id,
                output_text=output.message,
                metadata={
                    "cost_usd": total_cost,
                    "latency_ms": elapsed,
                    "model_id": result.responder_model,
                    "rounds_used": result.rounds_used,
                    "tools_called": result.tools_called,
                },
            ))
            self._log_quality_scores(trace_id, result)

            turn_id = await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
            self._schedule_background(input, ctx, output, turn_id)
            return output

        except Exception as exc:
            # One silent retry before any patient-visible error — but ONLY for
            # transient provider failures (timeouts, rate limits, brownouts).
            # A deterministic error would just double the spend; and the
            # memory-command path has side effects, so it must never re-run.
            from lib.ai_foundation.models.gateway import AllProvidersUnavailableError, _is_retryable

            transient = _is_retryable(exc) or isinstance(exc, AllProvidersUnavailableError)
            if not _is_retry and transient:
                logger.warning(
                    "HealthQueryAgent.run attempt failed, retrying once: %s", exc,
                )
                await asyncio.sleep(settings.PIPELINE_RETRY_BACKOFF_SECONDS)
                return await self.run(input, _is_retry=True)
            logger.exception("HealthQueryAgent.run failed after retry: %s", exc)
            return AgentOutput(
                message=await self._localize_text(
                    "I'm having trouble processing your request right now. Please try again.",
                    ctx, input=input,
                ),
                is_ready=False, trace_id=trace_id,
            )

    # ── Public: Proactive (event-triggered) ──────────────────────────────

    async def run_proactive(
        self,
        *,
        patient_id: str,
        event_summary: str,
        tier: ReasoningTier = ReasoningTier.STANDARD,
        refs: list[Any] | None = None,
        trace_id: str | None = None,
    ) -> ProactiveNarration:
        """Run the one brain on an event and return a push-shaped narration.

        Same reasoning engine, specialists, and evidence grounding as chat —
        there is no separate proactive brain. What differs: there is no user to
        clarify with, so intent triage is skipped; the event is the prompt; and
        the brain decides for itself whether the event is worth an unprompted
        push (``notify``). Copy is English (translated on delivery). The brain
        never sets clinical severity — the caller derives that from the trigger.
        """
        self._ensure_prompts()
        trace_id = trace_id or f"trc_{uuid4().hex[:16]}"

        # Cron/event path carries no request context — open the trace here.
        await _maybe_await(self.gateway.set_langfuse_context(
            session_id=f"proactive:{patient_id}",
            user_id=patient_id,
        ))
        await _maybe_await(self.gateway.langfuse_trace_input(
            trace_id=trace_id,
            name="proactive",
            input_text=event_summary,
            metadata={"mode": "proactive", "tier": getattr(tier, "value", str(tier))},
        ))

        agent_input = AgentInput(
            message=event_summary,
            context=AgentContext(patient_id=patient_id, refs=refs or [],
                                 metadata={"mode": "proactive"}),
        )
        ctx = await self._load_context(agent_input)

        result = await self.reasoning_engine.reason(
            user_message=event_summary,
            system_prompt=self._get_system_prompt("patient"),
            reasoning_prompt=self._render("hq_reasoning"),
            response_prompt=self._render("hq_proactive_response"),
            context=ctx,
            patient_ids=[patient_id],
            tier=tier,
            user_role="patient",
            trace_id=trace_id,
        )
        narration = await self._structure_proactive(result.response, trace_id=trace_id)
        await _maybe_await(self.gateway.langfuse_trace_output(
            trace_id=trace_id,
            output_text=getattr(narration, "body", "") or "",
            metadata={"notify": getattr(narration, "notify", None)},
        ))
        return narration

    async def _structure_proactive(
        self, analysis: str, *, trace_id: str | None = None,
    ) -> ProactiveNarration:
        """Turn the brain's grounded prose into the structured push payload.

        A pure formatting step — it must not add facts the analysis didn't
        state. If the analysis concluded no notification is warranted, notify
        is False.
        """
        messages = [
            {"role": "system", "content": (
                "Convert the analysis into a proactive push payload. Set notify=false "
                "if it concludes no notification is warranted. Never introduce a number, "
                "claim, or word the analysis did not already state. Keep the title "
                "≤50 chars and body ≤180 chars."
            )},
            {"role": "user", "content": analysis},
        ]
        narration, _meta = await self.gateway.extract(
            messages=messages, response_model=ProactiveNarration,
            task=ModelTask.STRUCTURED_ANALYSIS, trace_id=trace_id,
        )
        return narration

    # ── Public: SSE Streaming ─────────────────────────────────────────────

    async def run_stream(self, input: AgentInput) -> AsyncIterator[str]:
        # Fallbacks in case _init_pipeline fails before assigning the real ones
        # (the exception handlers below reference both).
        trace_id = f"trc_{uuid4().hex[:16]}"
        pipeline_start = time.perf_counter()
        ctx = None  # bound after _init_pipeline; error paths localize best-effort
        intent = None
        user_timestamp = None
        delta_sink: list[str] = []
        turn_saved = False

        try:
            yield sse_status(PipelineStage.EXTRACTING_INTENT, "Understanding the question...")
            try:
                pc = await self._init_pipeline(input)
            except Exception as exc:
                # Pre-content: nothing but a status event has been sent, so a
                # silent retry is safe. Post-token failures keep the existing
                # error/salvage path — retrying would duplicate content.
                logger.warning(
                    "run_stream init failed pre-content, retrying once: %s", exc,
                )
                await asyncio.sleep(settings.PIPELINE_RETRY_BACKOFF_SECONDS)
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
                output.message = await self._localize_text(output.message, ctx, input=input, cached=False)
                turn_id = await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                self._schedule_background(input, ctx, output, turn_id)
                yield sse_token(output.message)
                yield sse_done(SSEDonePayload(trace_id=trace_id, latency_ms=int((time.perf_counter() - pipeline_start) * 1000)))
                return

            if not intent.is_ready:
                msg = intent.clarification_msg or await self._localize_text(
                    _CLARIFY_FALLBACK, ctx, input=input,
                )
                clarify_suggestions = [s.model_dump(exclude_none=True) for s in intent.suggestions]
                output = AgentOutput(message=msg, is_ready=False, trace_id=trace_id,
                                     data={"pending_request": intent.awaits_log})
                if intent.awaits_log:
                    await self._register_pending_request(
                        input, intent.awaits_log, clarify_suggestions,
                        self._effective_language(input, ctx),
                    )
                turn_id = await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                self._schedule_background(input, ctx, output, turn_id)
                yield sse_token(msg)
                yield sse_done(SSEDonePayload(
                    suggestions=clarify_suggestions,
                    trace_id=trace_id,
                    latency_ms=int((time.perf_counter() - pipeline_start) * 1000),
                ))
                return

            # ── Route: single-agent vs multi-agent (streaming) ──
            patient_ids = self._resolve_patient_ids(input)
            system_prompt = self._get_system_prompt(input.context.user_role)
            response_language = self._effective_language(input, ctx)
            reasoning_prompt, response_prompt = self._get_reasoning_prompts(input, response_language)
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
                    delta_sink=delta_sink,
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
                    # Expand to the full domain family so a glucose query
                    # about spikes/lows fetches the event records, not just
                    # summaries (the single-agent path otherwise trusts the
                    # extractor's narrow pick — see expand_to_domain_types).
                    intent_data_types=[dt.value for dt in expand_to_domain_types(intent.data_types)],
                    patient_names=ctx.patient_names,
                    user_role=input.context.user_role,
                    trace_id=trace_id,
                    delta_sink=delta_sink,
                )

            async with asyncio.timeout(settings.STREAMING_PIPELINE_TIMEOUT_SECONDS):
                async for event in event_source:
                    # The engine yields a structured terminal payload — intercept
                    # it to save the turn and inject suggestions, then emit our
                    # own done event.
                    if isinstance(event, SSEDonePayload):
                        engine_data = event.data or {}
                        raw_text = engine_data.get("full_response", "")
                        raw_text, awaited = extract_await(raw_text)
                        awaited = awaited or intent.awaits_log
                        stream_suggestions = [s.model_dump(exclude_none=True) for s in intent.suggestions]
                        if awaited:
                            await self._register_pending_request(input, awaited, stream_suggestions, response_language)
                        engine_data["pending_request"] = awaited
                        # Bubble protocol: legacy clients keep a clean single
                        # string; new clients render data.messages as bubbles.
                        full_text = strip_bubbles(raw_text)
                        engine_data["full_response"] = full_text
                        engine_data["messages"] = split_bubbles(raw_text)
                        intent_cost = safe_cost(meta)
                        total_cost = (event.cost_usd or 0.0) + intent_cost
                        elapsed = int((time.perf_counter() - pipeline_start) * 1000)

                        output = AgentOutput(
                            message=full_text, is_ready=True,
                            trace_id=trace_id,
                            cost_usd=total_cost,
                            latency_ms=elapsed,
                            model_id=event.model_id,
                            data={
                                "messages": engine_data.get("messages"),
                                "pending_request": awaited,
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
                            await _maybe_await(self.gateway.langfuse_trace_output(
                                trace_id=trace_id,
                                output_text=full_text,
                                metadata={
                                    "cost_usd": total_cost,
                                    "latency_ms": elapsed,
                                    "model_id": event.model_id,
                                    "rounds_used": engine_data.get("rounds_used"),
                                    "tools_called": engine_data.get("tools_called"),
                                },
                            ))
                        self._log_quality_scores_from_data(trace_id, engine_data)
                        turn_id = await self._save_turn(input, output, intent, user_timestamp=user_timestamp)
                        turn_saved = True
                        self._schedule_background(input, ctx, output, turn_id)

                        # Emit our own done event with suggestions and trace
                        yield sse_done(SSEDonePayload(
                            suggestions=stream_suggestions,
                            trace_id=trace_id,
                            cost_usd=total_cost,
                            latency_ms=elapsed,
                            model_id=event.model_id,
                            data=engine_data,
                        ))
                        continue

                    yield event

        except TimeoutError:
            elapsed = int((time.perf_counter() - pipeline_start) * 1000)
            logger.error("Streaming pipeline timed out after %dms (limit=%ds)",
                         elapsed, settings.STREAMING_PIPELINE_TIMEOUT_SECONDS)
            yield sse_error(
                message=await self._localize_text(
                    "This query is taking longer than expected. Please try a simpler question or try again.",
                    ctx, input=input,
                ),
                code="pipeline_timeout",
            )
        except Exception as exc:
            logger.exception("HealthQueryAgent.run_stream failed: %s", exc)
            yield sse_error(
                message=await self._localize_text("I'm having trouble right now.", ctx, input=input),
                code="agent_error",
                fallback_text=await self._localize_text("Please try again in a moment.", ctx, input=input),
            )
        finally:
            # Client disconnect (GeneratorExit) mid-stream: history must
            # still record what the user read — their message plus the
            # delivered partial. (No yields here — only awaits are legal
            # during async-generator finalization.)
            if delta_sink and not turn_saved and intent is not None:
                try:
                    raw = "".join(delta_sink)
                    clean, _ = extract_await(raw)
                    partial = strip_bubbles(clean)
                    if partial.strip():
                        salvage = AgentOutput(
                            message=partial, is_ready=True, trace_id=trace_id,
                            data={"messages": split_bubbles(clean), "interrupted": True},
                        )
                        await self._save_turn(
                            input, salvage, intent, user_timestamp=user_timestamp,
                        )
                        logger.info("Salvaged interrupted stream turn (thread=%s, %d chars)",
                                    input.context.thread_id, len(partial))
                except Exception as salvage_exc:
                    logger.warning("Stream salvage failed: %s", salvage_exc)

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
        # Device local time wins; fall back to the server-computed value from
        # the patient's stored timezone so the agent is never time-blind.
        ctx.local_time = (input.context.metadata or {}).get("local_time") or ctx.local_time
        intent, meta = await self._extract_intent(input, ctx, trace_id=trace_id)
        # Force chips into the patient's language before any path dumps them —
        # the extractor is told to write suggestions in-language but doesn't
        # reliably obey for short labels. One place, so run(), run_stream(), and
        # the clarification path all inherit it.
        await self._localize_suggestions(intent, self._effective_language(input, ctx))

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
            refs=input.context.refs,
        )

    async def _extract_intent(self, input: AgentInput, ctx: Any, *, trace_id: str | None = None) -> tuple[QueryIntent, Any]:
        self._ensure_prompts()
        system_prompt = self._get_system_prompt(input.context.user_role)
        intent_prompt = self._render("hq_intent_extraction")

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": intent_prompt},
        ]

        # Inject local time for accurate date resolution (device value, else
        # server-computed from the patient's stored timezone)
        local_time = (input.context.metadata or {}).get("local_time") or getattr(ctx, "local_time", None)
        if local_time:
            messages.append({"role": "system", "content": (
                f"User's local time: {local_time}. "
                f"Use THIS for resolving 'today', 'yesterday', 'this week', etc."
            )})

        # Inject pinned refs so intent extraction knows what the user is asking about.
        for ref in getattr(ctx, "pinned_refs", []) or []:
            parts = [f"User is asking about {ref.type.value} \"{ref.title}\"."]
            if ref.occurred_at:
                parts.append(f"Occurred: {ref.occurred_at}.")
            parts.append("Anchor intent extraction to this entity.")
            messages.append({"role": "system", "content": " ".join(parts)})

        if ctx.thread_summary:
            messages.append({"role": "system", "content": f"Conversation summary:\n{ctx.thread_summary}"})

        if input.context.user_role in ("care_provider", "research") and ctx.patient_names:
            names = list(ctx.patient_names.values())
            if len(names) > 1:
                messages.append({"role": "system", "content": (
                    f"You are analyzing a panel of {len(names)} patients: {', '.join(names)}. "
                    f"Ensure intent extraction accounts for ALL patients, not just one. "
                    f"In suggestions, use patient names, NEVER use 'my' or 'your'."
                )})
            else:
                messages.append({"role": "system", "content": (
                    f"The user is a {input.context.user_role} asking about: {', '.join(names)}. "
                    f"In suggestions, use patient names, NEVER use 'my' or 'your'."
                )})

        # Voice mirrors the spoken language (metadata.voice_language, set
        # per-utterance and already constrained to what TTS can speak);
        # text channels follow the stored preference.
        lang = self._effective_language(input, ctx)
        if lang != DEFAULT_AI_LANGUAGE:
            lang_name = ai_language_name(lang)
            messages.append({"role": "system", "content": (
                f"The patient's preferred language is {lang_name}. Write "
                f"suggestion labels, suggestion descriptions, and any "
                f"clarification_msg in {lang_name}. All other extraction "
                f"fields stay in English. {RESPECTFUL_REGISTER_INSTRUCTION}"
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
            trace_id=trace_id,
        )

        return intent, meta

    # ── Persistence + background ──────────────────────────────────────────

    async def _save_turn(
        self, input: AgentInput, output: AgentOutput, intent: QueryIntent,
        user_timestamp: Any = None,
    ) -> Any | None:
        """Returns the saved assistant turn's id (for targeted late metadata)."""
        if not self.persistence:
            return None
        # Persist the bubble split so history renders the same messages the
        # user watched stream in — content stays the joined full text.
        bubbles = (output.data or {}).get("messages")
        return await self.persistence.save_turn(
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
                "input_mode": input.context.metadata.get("output_mode", "text"),
                "channel": input.context.metadata.get("channel", "app"),
                "audio_url": input.context.metadata.get("audio_url"),
                **({"bubbles": bubbles} if bubbles and len(bubbles) > 1 else {}),
                **({"interrupted": True} if (output.data or {}).get("interrupted") else {}),
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

    # Canonical English chip labels — non-English users get these through
    # the TranslationService (cached), same path as every other AI string.
    _AWAIT_CHIP_LABELS = {
        "meal": "Log a meal",
        "smbg": "Log glucose reading",
        "symptom": "Log symptoms",
        "sleep": "Log sleep",
        "mood": "Log mood",
        "workout": "Log workout",
    }

    async def _register_pending_request(
        self, input: AgentInput, entity_type: str, suggestions: list[dict],
        language: str = DEFAULT_AI_LANGUAGE,
    ) -> None:
        """Persist the data-ask (fire-and-forget) + add an action chip so the
        app can open the right logging sheet in one tap."""
        if self.persistence:
            self._spawn_background(
                self.persistence.record_pending_request(
                thread_id=input.context.thread_id, entity_type=entity_type,
                ),
                name="pending_request", thread_id=input.context.thread_id or "",
            )
        label = self._AWAIT_CHIP_LABELS.get(entity_type, f"Log {entity_type}")
        if language != DEFAULT_AI_LANGUAGE and self.translator:
            label = await self.translator.translate_cached(label, language, terse=True)
        suggestions.insert(0, {
            "action": f"log_{entity_type}",
            "label": label,
            "description": label,
        })

    def _schedule_background(
        self, input: AgentInput, ctx: Any = None, output: Any = None,
        turn_id: Any = None,
    ) -> None:
        """Schedule background tasks with timeout and error handling."""
        thread_id = input.context.thread_id or ""
        # English audit copy: the invariant is that an English version of every
        # AI reply always exists. Chat generates in the preferred language, so
        # the English copy is attached to the saved turn (by id — a fast
        # follow-up must not receive the previous turn's translation).
        lang = self._effective_language(input, ctx)
        message = getattr(output, "message", None)
        if (
            lang != DEFAULT_AI_LANGUAGE and message and turn_id is not None
            and self.translator and self.persistence
        ):
            turn_bubbles = (getattr(output, "data", None) or {}).get("messages")
            self._spawn_background(
                self._attach_english_copy(
                turn_id, message, lang, turn_bubbles,
                thread_id=thread_id, user_id=input.context.user_id,
                ),
                name="audit_translation", thread_id=thread_id,
            )
        if self.persistence:
            self._spawn_background(
                self.persistence.compact_if_needed(
                thread_id=input.context.thread_id, agent_id=self.agent_id,
                patient_ids=input.context.patient_ids,
                ),
                name="compaction", thread_id=thread_id,
            )
        if self.fact_extractor:
            pid = self._resolve_single_pid(input)
            if pid:
                # The agent's reply the user is responding to — short answers
                # ("yes, around 1am") are meaningless without it.
                preceding = None
                for turn in reversed(getattr(ctx, "history", None) or []):
                    if turn.get("role") == "assistant":
                        preceding = turn.get("content")
                        break
                self._spawn_background(
                    self.fact_extractor.extract_if_needed(
                    message=input.message, patient_id=pid, agent_id=self.agent_id,
                    preceding_assistant_message=preceding,
                    ),
                    name="fact_extraction", thread_id=thread_id,
                )

    async def _attach_english_copy(
        self, turn_id: Any, message: str, lang: str, bubbles: list[str] | None = None,
        *, thread_id: str | None = None, user_id: str | None = None,
    ) -> None:
        """Translate the reply the user saw back to English and attach it to
        exactly the turn it belongs to (audit invariant).

        Multi-bubble turns are translated WITH the [[BUBBLE]] markers in place
        (the fidelity guards keep them intact) and split back, so every bubble
        gets its own aligned English copy — the app's "View in English" works
        per bubble, not just on the last one.
        """
        from lib.ai_foundation.agents.core.bubbles import BUBBLE_DELIMITER

        source = (
            f"\n{BUBBLE_DELIMITER}\n".join(bubbles)
            if bubbles and len(bubbles) > 1
            else message
        )
        english = await self.translator.translate(source, "en", source_lang=lang)
        if not english or english == source:
            return
        en_bubbles = split_bubbles(english)
        await self.persistence.attach_translation(
            turn_id=turn_id, language=lang,
            translations={"en": strip_bubbles(english)},
            en_bubbles=en_bubbles if len(en_bubbles) > 1 else None,
        )
        # Nudge the open chat (silent data message) so "View in English"
        # appears on the fresh reply without a reopen. Best-effort.
        if user_id and thread_id:
            try:
                from lib.services.fcm_service import FCMService

                await FCMService().send_fcm_data_to_user_devices(
                    user_id=user_id,
                    data={"type": "chat_thread_updated", "thread_id": thread_id,
                          "reason": "translation"},
                )
            except Exception as exc:
                logger.debug("chat_thread_updated nudge failed: %s", exc)

    @staticmethod
    def _effective_language(input: AgentInput, ctx: Any) -> str:
        """The language this reply must be written in.

        Voice sessions mirror the SPOKEN language (set per-utterance by the
        voice orchestrator as metadata.voice_language — speaking is itself a
        language choice and voice has no "view in English" toggle). Text
        channels follow the stored preference on the context.
        """
        voice_lang = (input.context.metadata or {}).get("voice_language")
        if voice_lang:
            return voice_lang
        return getattr(ctx, "response_language", DEFAULT_AI_LANGUAGE)

    async def _localize_text(
        self, text: str, ctx: Any, *, input: AgentInput | None = None, cached: bool = True,
    ) -> str:
        """English strings built outside the responder (memory replies,
        clarification/error fallbacks) shown to a non-English user go through
        the translator — never hardcoded per-language, never silently English.

        ``cached=True`` for fixed strings; False for dynamic content
        (e.g. the memory list) so unique strings don't pollute the cache.
        """
        lang = (
            self._effective_language(input, ctx) if input is not None
            else getattr(ctx, "response_language", DEFAULT_AI_LANGUAGE)
        )
        if lang == DEFAULT_AI_LANGUAGE or not self.translator or not text:
            return text
        try:
            if cached:
                return await self.translator.translate_cached(text, lang)
            return await self.translator.translate(text, lang)
        except Exception:
            return text  # provider down → English beats nothing

    async def _localize_suggestions(self, intent: Any, lang: str) -> None:
        """Force suggestion chips into the patient's language via the TERSE
        translation path — the prose translator expands imperative labels into
        lists, so chips get the short-UI prompt with an expansion guard. Label
        cached (chip labels recur); description live (it becomes the next user
        message, so it must be in-language too). Per-chip failure leaves that
        chip unchanged rather than dropping the suggestion."""
        if lang == DEFAULT_AI_LANGUAGE or not self.translator or not intent.suggestions:
            return

        async def _one(s: Any) -> None:
            try:
                s.label, s.description = await asyncio.gather(
                    self.translator.translate_cached(s.label, lang, terse=True),
                    self.translator.translate(s.description, lang, terse=True),
                )
            except Exception as exc:
                # English chip ships (better than none) — but never silently.
                logger.warning("Suggestion chip translation failed (%s): %s", lang, exc)

        await asyncio.gather(*(_one(s) for s in intent.suggestions))

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
        # `is None`, not truthiness — an EMPTY PromptRegistry is falsy
        # (__len__ == 0) and would skip registration forever.
        if self._prompts_registered or self.prompts is None:
            return
        if "hq_system_patient" not in self.prompts:
            self.prompts.register_directory(_PROMPTS_DIR, namespace="health_query")
        self._prompts_registered = True

    def _render(self, template_name: str, **extra_vars: str) -> str:
        """Render a prompt with common variables (available_data_types, current_time)."""
        from lib.ai_foundation.agents.health_query.contracts import AVAILABLE_HEALTH_DOMAINS
        template = self.prompts.get(template_name)
        from lib.ai_foundation.agents.core.bubbles import AWAIT_ENTITY_TYPES

        return template.render(
            available_data_types=AVAILABLE_HEALTH_DOMAINS,
            # single source of truth: bubbles.AWAIT_ENTITY_TYPES — a prompt
            # list that drifts from the regex silently kills the closed loop
            await_entity_types=", ".join(AWAIT_ENTITY_TYPES),
            # Local prompts must not reference this — a time-varying value
            # in the system prompt defeats provider prefix caching (time
            # rides in the per-turn local-time context line). Supplied only
            # so older Langfuse prompt versions render until synced.
            current_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            **extra_vars,
        )

    def _get_system_prompt(self, user_role: str) -> str:
        """Get system prompt, cached per role. The per-minute cache key is a
        refresh TTL (picks up Langfuse prompt edits); the rendered content
        itself is time-free and byte-stable, so provider prefix caching works."""
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

    def _get_reasoning_prompts(
        self, input: AgentInput | None = None, response_language: str = DEFAULT_AI_LANGUAGE,
    ) -> tuple[str, str]:
        """Return (reasoning_prompt, response_prompt) for the engine.

        When input.context.metadata contains output_mode='voice', voice-
        optimised prompts are used: conversational reasoning thoughts that
        sound natural when spoken aloud, and a brief response with no markdown.

        ``response_language``: the patient's preferred AI language — rendered
        into the response prompt so the agent writes directly in it (voice
        stays English for now; TTS language support is v2).
        """
        self._ensure_prompts()
        output_mode = (
            input.context.metadata.get("output_mode") if input else None
        )
        channel = (
            input.context.metadata.get("channel") if input else None
        )

        lang_instruction = ""
        voice_lang_instruction = ""
        if response_language != DEFAULT_AI_LANGUAGE:
            lang_name = ai_language_name(response_language)
            lang_instruction = (
                f"\n## Response Language\n"
                f"Write your ENTIRE response in {lang_name} — this is the patient's "
                f"chosen language. {NUMBER_FIDELITY_INSTRUCTION} "
                f"Table syntax stays markdown; translate only the cell text. "
                f"{RESPECTFUL_REGISTER_INSTRUCTION}\n"
            )
            # Voice mirrors the SPOKEN language — reply how the patient spoke.
            voice_lang_instruction = (
                f"\n## Response Language\n"
                f"The patient spoke in {lang_name} — reply ENTIRELY in {lang_name}, "
                f"natural and speakable. Say numbers with their units plainly; "
                f"keep medication names as-is. {RESPECTFUL_REGISTER_INSTRUCTION}\n"
            )

        if output_mode == "voice":
            reasoning = self._render("hq_reasoning_voice")
            response = self._render(
                "hq_final_response_voice",
                response_language_instruction=voice_lang_instruction,
            )
        elif channel == "whatsapp":
            reasoning = self._render("hq_reasoning")
            response = self._render(
                "hq_final_response_whatsapp",
                response_language_instruction=lang_instruction,
            )
        else:
            reasoning = self._render("hq_reasoning")
            response = self._render(
                "hq_final_response",
                response_language_instruction=lang_instruction,
            )
        return reasoning, response

    def _log_quality_scores(self, trace_id: str, result: Any) -> None:
        """Log coverage/reflection scores to Langfuse for quality monitoring."""
        if result.coverage_confidence is not None:
            self.gateway.log_score(trace_id=trace_id, name="coverage_confidence", value=result.coverage_confidence)
        if result.reflection_confidence is not None:
            self.gateway.log_score(trace_id=trace_id, name="reflection_confidence", value=result.reflection_confidence)
        if result.data_gaps:
            self.gateway.log_score(trace_id=trace_id, name="data_gaps_count", value=float(len(result.data_gaps)),
                                   comment="; ".join(result.data_gaps))
        if result.data_conflicts:
            self.gateway.log_score(trace_id=trace_id, name="data_conflicts_count", value=float(len(result.data_conflicts)),
                                   comment="; ".join(result.data_conflicts))

    def _log_quality_scores_from_data(self, trace_id: str, engine_data: dict) -> None:
        """Log quality scores from streaming done payload data dict."""
        cc = engine_data.get("coverage_confidence")
        if cc is not None:
            self.gateway.log_score(trace_id=trace_id, name="coverage_confidence", value=cc)
        rc = engine_data.get("reflection_confidence")
        if rc is not None:
            self.gateway.log_score(trace_id=trace_id, name="reflection_confidence", value=rc)
        gaps = engine_data.get("data_gaps")
        if gaps:
            self.gateway.log_score(trace_id=trace_id, name="data_gaps_count", value=float(len(gaps)),
                                   comment="; ".join(gaps))
        conflicts = engine_data.get("data_conflicts")
        if conflicts:
            self.gateway.log_score(trace_id=trace_id, name="data_conflicts_count", value=float(len(conflicts)),
                                   comment="; ".join(conflicts))

    def _build_clarification(self, intent: QueryIntent, meta: Any) -> AgentOutput:
        return AgentOutput(
            message=intent.clarification_msg or _CLARIFY_FALLBACK,
            is_ready=False,
            suggestions=[s.model_dump(exclude_none=True) for s in intent.suggestions],
            data={"data_types": [dt.value for dt in intent.data_types], "confidence": intent.confidence,
                  "pending_request": intent.awaits_log},
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
        """Resolve reasoning tier from input context or default.

        Panel queries (multiple patients) are auto-upgraded to at least ADVANCED
        regardless of the requested tier — cost is not a concern for multi-patient
        care_provider / research queries and the extra tool-call budget is needed
        to achieve adequate per-patient coverage.
        """
        tier_str = (input.context.metadata or {}).get("tier", settings.REASONING_DEFAULT_TIER)
        try:
            tier = ReasoningTier(tier_str)
        except ValueError:
            tier = ReasoningTier.STANDARD

        patient_ids = input.context.patient_ids or []
        if len(patient_ids) > 1:
            # Upgrade: BASIC → ADVANCED, STANDARD → ADVANCED; leave UNLIMITED as-is
            _PANEL_MIN = ReasoningTier.ADVANCED
            _ORDER = [ReasoningTier.BASIC, ReasoningTier.STANDARD, ReasoningTier.ADVANCED, ReasoningTier.UNLIMITED]
            if _ORDER.index(tier) < _ORDER.index(_PANEL_MIN):
                tier = _PANEL_MIN

        return tier

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
