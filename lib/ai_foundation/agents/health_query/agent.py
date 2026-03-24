"""
Health Query Agent — clean implementation on the AI Foundation.

Pipeline:
    1. Load patient context (memory facts, conversation history)
    2. Extract intent via LLM (ModelGateway.extract → QueryIntent)
    3. If not ready → return clarification
    4. Retrieve health data (CompositeRetriever)
    5. Build analysis snapshot
    6. Generate response via LLM (ModelGateway.stream or .complete)
    7. Persist trace, memory, conversation turn
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from lib.ai_foundation.agents.base import BaseAgent
from lib.ai_foundation.agents.state import AgentInput, AgentOutput
from lib.ai_foundation.models.registry import ModelTask
from lib.ai_foundation.retrieval.base import RetrievalRequest
from lib.ai_foundation.streaming.sse import (
    PipelineStage,
    SSEDonePayload,
    sse_done,
    sse_error,
    sse_intent,
    sse_status,
    sse_token,
)

from .contracts import (
    DomainName,
    HealthDataType,
    QueryIntent,
    QueryResponse,
    ResponseMode,
    SuggestedAction,
)

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Data type → domain mapping
_DATA_TYPE_DOMAINS: dict[str, DomainName] = {
    "cgm_range_stats": DomainName.CGM,
    "cgm_summary_stats": DomainName.CGM,
    "hyper_stats": DomainName.CGM,
    "hypo_stats": DomainName.CGM,
    "rapid_spike_stats": DomainName.CGM,
    "rapid_drop_stats": DomainName.CGM,
    "hyper_event": DomainName.CGM,
    "hypo_event": DomainName.CGM,
    "rapid_spike_event": DomainName.CGM,
    "rapid_drop_event": DomainName.CGM,
    "time_period_stats": DomainName.CGM,
    "agp_point": DomainName.CGM,
    "cgm_semantic_window": DomainName.CGM,
    "smbg": DomainName.SMBG,
    "meal": DomainName.MEAL,
    "fitness_overview": DomainName.FITNESS,
    "fitness_activity_distribution": DomainName.FITNESS,
    "fitness_inactive_periods": DomainName.FITNESS,
    "profile": DomainName.PROFILE,
    "patient_document": DomainName.DOCUMENTS,
}


class HealthQueryAgent(BaseAgent):
    """Foundation-native health query agent.

    Uses ModelGateway for all LLM calls, CompositeRetriever for data,
    MemoryStore for patient facts, TraceCollector for observability,
    and native SSE streaming.
    """

    agent_id = "health_query_v3"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._prompts_registered = False

    # -- Public API ---------------------------------------------------------

    async def run(self, input: AgentInput) -> AgentOutput:
        """Full pipeline: intent → retrieve → analyze → respond."""
        pipeline_start = time.perf_counter()
        trace = None

        if self.tracer:
            trace = self.tracer.start_trace(
                self.agent_id,
                patient_id=input.context.patient_id,
                thread_id=input.context.thread_id,
                user_role=input.context.user_role,
            )

        try:
            # 1. Load context
            memory_facts = await self._load_patient_facts(input)
            history = await self._load_conversation_history(input)

            # 2. Extract intent
            intent, intent_meta = await self._extract_intent(input, memory_facts, history)

            # 3. If not ready → clarification
            if not intent.is_ready:
                output = self._build_clarification_output(intent, intent_meta)
                await self._persist_turn(input, output, intent)
                return output

            # 4. Retrieve data
            retrieved = await self._retrieve_data(input, intent)

            # 5. Build analysis
            analysis = self._build_analysis(intent, retrieved)

            # 6. Generate response
            response_text = await self._generate_response(input, intent, analysis, memory_facts, history)

            # 7. Build output
            elapsed_ms = int((time.perf_counter() - pipeline_start) * 1000)
            output = AgentOutput(
                message=response_text,
                is_ready=True,
                suggestions=[s.model_dump() for s in intent.suggestions],
                data={
                    "data_types": [dt.value for dt in intent.data_types],
                    "date_range": intent.date_range.model_dump(mode="json") if intent.date_range else None,
                    "confidence": intent.confidence,
                    "domains": list({_DATA_TYPE_DOMAINS.get(dt.value, DomainName.CGM).value for dt in intent.data_types}),
                    "retrieval_count": len(retrieved),
                },
                trace_id=trace.trace_id if trace else None,
                cost_usd=intent_meta.usage.cost.total_cost if intent_meta else None,
                latency_ms=elapsed_ms,
                model_id=intent_meta.model_id if intent_meta else None,
            )

            await self._persist_turn(input, output, intent)
            return output

        except Exception as exc:
            logger.exception("HealthQueryAgent.run failed: %s", exc)
            return AgentOutput(
                message="I'm having trouble processing your request right now. Please try again.",
                is_ready=False,
                trace_id=trace.trace_id if trace else None,
            )
        finally:
            if self.tracer and trace:
                await self.tracer.finish_trace()

    async def run_stream(self, input: AgentInput) -> AsyncIterator[str]:
        """SSE streaming pipeline."""
        pipeline_start = time.perf_counter()
        trace = None

        if self.tracer:
            trace = self.tracer.start_trace(
                self.agent_id,
                patient_id=input.context.patient_id,
                thread_id=input.context.thread_id,
            )

        try:
            # Stage 1: Intent
            yield sse_status(PipelineStage.EXTRACTING_INTENT, "Understanding your question...")

            memory_facts = await self._load_patient_facts(input)
            history = await self._load_conversation_history(input)
            intent, intent_meta = await self._extract_intent(input, memory_facts, history)

            yield sse_intent(intent.model_dump(mode="json", exclude_none=True))

            if not intent.is_ready:
                yield sse_token(intent.clarification_msg or "Could you tell me more about what you'd like to know?")
                yield sse_done(SSEDonePayload(
                    suggestions=[s.model_dump() for s in intent.suggestions],
                    trace_id=trace.trace_id if trace else None,
                    latency_ms=int((time.perf_counter() - pipeline_start) * 1000),
                ))
                return

            # Stage 2: Retrieve
            yield sse_status(PipelineStage.FETCHING_DATA, "Pulling your health data...")

            retrieved = await self._retrieve_data(input, intent)
            analysis = self._build_analysis(intent, retrieved)

            # Stage 3: Generate (streaming)
            yield sse_status(PipelineStage.GENERATING_RESPONSE, "Generating response...")

            full_text_parts: list[str] = []
            response_messages = self._build_response_messages(input, intent, analysis, memory_facts, history)

            first_token_sent = False
            async for chunk in self.gateway.stream(
                messages=response_messages,
                task=ModelTask.RESPONSE_GENERATION,
            ):
                if chunk.delta:
                    if not first_token_sent and self.tracer:
                        self.tracer.record_first_token()
                        first_token_sent = True
                    full_text_parts.append(chunk.delta)
                    yield sse_token(chunk.delta)

            # Stage 4: Done
            elapsed_ms = int((time.perf_counter() - pipeline_start) * 1000)
            yield sse_done(SSEDonePayload(
                suggestions=[s.model_dump() for s in intent.suggestions],
                trace_id=trace.trace_id if trace else None,
                cost_usd=intent_meta.usage.cost.total_cost if intent_meta else None,
                latency_ms=elapsed_ms,
                model_id=intent_meta.model_id if intent_meta else None,
                data={
                    "data_types": [dt.value for dt in intent.data_types],
                    "retrieval_count": len(retrieved),
                },
            ))

            # Persist
            full_text = "".join(full_text_parts)
            output = AgentOutput(message=full_text, is_ready=True, trace_id=trace.trace_id if trace else None)
            await self._persist_turn(input, output, intent)

        except Exception as exc:
            logger.exception("HealthQueryAgent.run_stream failed: %s", exc)
            yield sse_error(
                message="I'm having trouble processing your request right now.",
                code="agent_error",
                fallback_text="Please try again in a moment.",
            )
        finally:
            if self.tracer and trace:
                await self.tracer.finish_trace()

    # -- Pipeline steps (private) -------------------------------------------

    async def _load_patient_facts(self, input: AgentInput) -> list[dict]:
        """Load patient memory facts from the shared memory store."""
        if not self.memory or not input.context.patient_id:
            return []
        try:
            facts = await self.memory.get_patient_facts(input.context.patient_id)
            return [f.model_dump(mode="json") for f in facts]
        except Exception as exc:
            logger.warning("Failed to load patient facts: %s", exc)
            return []

    async def _load_conversation_history(self, input: AgentInput) -> list[dict[str, str]]:
        """Load recent conversation turns from the shared memory store."""
        if not self.memory or not input.context.thread_id:
            return []
        try:
            turns = await self.memory.get_thread_turns(input.context.thread_id, limit=10)
            return [{"role": t.role, "content": t.content} for t in turns]
        except Exception as exc:
            logger.warning("Failed to load conversation history: %s", exc)
            return []

    async def _extract_intent(
        self,
        input: AgentInput,
        memory_facts: list[dict],
        history: list[dict[str, str]],
    ) -> tuple[QueryIntent, Any]:
        """Extract structured intent from the user's message."""
        self._ensure_prompts()

        system_prompt = self._get_system_prompt(input.context.user_role)
        intent_prompt = self.prompts.get("hq_intent_extraction").body

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": intent_prompt},
        ]

        # Inject patient memory as context
        if memory_facts:
            compact = [f"- {f['key']}: {f['value']}" for f in memory_facts[:8]]
            messages.append({
                "role": "system",
                "content": "Patient memory facts:\n" + "\n".join(compact),
            })

        # Add conversation history
        messages.extend(history[-8:])

        # Current user message
        messages.append({"role": "user", "content": input.message})

        if self.tracer:
            async with self.tracer.span("intent_extraction") as span:
                intent, meta = await self.gateway.extract(
                    messages=messages,
                    response_model=QueryIntent,
                    task=ModelTask.INTENT_EXTRACTION,
                )
                span.model_id = meta.model_id
                span.tokens_in = meta.usage.input_tokens
                span.tokens_out = meta.usage.output_tokens
                span.cost_usd = meta.usage.cost.total_cost
        else:
            intent, meta = await self.gateway.extract(
                messages=messages,
                response_model=QueryIntent,
                task=ModelTask.INTENT_EXTRACTION,
            )

        return intent, meta

    async def _retrieve_data(
        self,
        input: AgentInput,
        intent: QueryIntent,
    ) -> list[dict[str, Any]]:
        """Retrieve health data using the composite retriever."""
        if not self.retriever:
            return []

        patient_ids = input.context.patient_ids or (
            [input.context.patient_id] if input.context.patient_id else []
        )

        request = RetrievalRequest(
            query=input.message,
            patient_ids=patient_ids,
            data_types=[dt.value for dt in intent.data_types],
            date_start=intent.date_range.start.isoformat() if intent.date_range else None,
            date_end=intent.date_range.end.isoformat() if intent.date_range else None,
            limit=24,
        )

        if self.tracer:
            async with self.tracer.span("data_retrieval") as span:
                result = await self.retriever.retrieve(request)
                span.tags["sources"] = ",".join(result.executed_sources)
                span.tags["result_count"] = str(len(result.items))
                if result.degraded_sources:
                    span.tags["degraded"] = ",".join(result.degraded_sources)
        else:
            result = await self.retriever.retrieve(request)

        return [item.payload for item in result.items]

    def _build_analysis(
        self,
        intent: QueryIntent,
        retrieved: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build a structured analysis snapshot from retrieved data."""
        domains = list({
            _DATA_TYPE_DOMAINS.get(dt.value, DomainName.CGM).value
            for dt in intent.data_types
        })

        # Group by data_type
        by_type: dict[str, list[dict]] = {}
        for item in retrieved:
            dt = item.get("data_type", "unknown")
            by_type.setdefault(dt, []).append(item)

        # Build highlights
        highlights: list[str] = []
        for dt, items in by_type.items():
            highlights.append(f"{dt}: {len(items)} records found")

        return {
            "domains": domains,
            "record_count": len(retrieved),
            "by_data_type": {k: len(v) for k, v in by_type.items()},
            "highlights": highlights,
            "data": retrieved[:20],  # cap for context window
        }

    async def _generate_response(
        self,
        input: AgentInput,
        intent: QueryIntent,
        analysis: dict[str, Any],
        memory_facts: list[dict],
        history: list[dict[str, str]],
    ) -> str:
        """Generate the final conversational response."""
        messages = self._build_response_messages(input, intent, analysis, memory_facts, history)

        if self.tracer:
            async with self.tracer.span("response_generation") as span:
                response = await self.gateway.complete(
                    messages=messages,
                    task=ModelTask.RESPONSE_GENERATION,
                )
                span.model_id = response.model_id
                span.tokens_in = response.usage.input_tokens
                span.tokens_out = response.usage.output_tokens
                span.cost_usd = response.usage.cost.total_cost
        else:
            response = await self.gateway.complete(
                messages=messages,
                task=ModelTask.RESPONSE_GENERATION,
            )

        return response.content

    def _build_response_messages(
        self,
        input: AgentInput,
        intent: QueryIntent,
        analysis: dict[str, Any],
        memory_facts: list[dict],
        history: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Assemble the message list for response generation."""
        self._ensure_prompts()

        system_prompt = self._get_system_prompt(input.context.user_role)
        response_prompt = self.prompts.get("hq_response_generation").body

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": response_prompt},
            {"role": "system", "content": f"[Structured analysis: {json.dumps(analysis, default=str)}]"},
        ]

        if memory_facts:
            compact = [f"- {f['key']}: {f['value']}" for f in memory_facts[:8]]
            messages.append({
                "role": "system",
                "content": "Patient context:\n" + "\n".join(compact),
            })

        messages.extend(history[-10:])
        messages.append({"role": "user", "content": input.message})

        return messages

    # -- Helpers ------------------------------------------------------------

    def _ensure_prompts(self) -> None:
        """Register prompts on first use."""
        if self._prompts_registered or not self.prompts:
            return
        if "hq_system_patient" not in self.prompts:
            self.prompts.register_directory(_PROMPTS_DIR, namespace="health_query")
        self._prompts_registered = True

    def _get_system_prompt(self, user_role: str) -> str:
        """Get the role-appropriate system prompt."""
        name = "hq_system_care_provider" if user_role == "care_provider" else "hq_system_patient"
        template = self.prompts.get(name)
        return template.render(current_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    def _build_clarification_output(self, intent: QueryIntent, meta: Any) -> AgentOutput:
        """Build output for when the intent is not ready."""
        return AgentOutput(
            message=intent.clarification_msg or "Could you tell me more about what you'd like to know?",
            is_ready=False,
            suggestions=[s.model_dump() for s in intent.suggestions],
            data={
                "data_types": [dt.value for dt in intent.data_types],
                "confidence": intent.confidence,
            },
            trace_id=meta.trace_id if meta else None,
            cost_usd=meta.usage.cost.total_cost if meta else None,
            model_id=meta.model_id if meta else None,
        )

    async def _persist_turn(
        self,
        input: AgentInput,
        output: AgentOutput,
        intent: QueryIntent,
    ) -> None:
        """Save conversation turns to the shared memory store."""
        if not self.memory or not input.context.thread_id:
            return

        from lib.ai_foundation.memory.base import ConversationTurn

        try:
            # Save user turn
            await self.memory.append_turn(
                input.context.thread_id,
                ConversationTurn(
                    role="user",
                    content=input.message,
                    agent_id=self.agent_id,
                ),
            )
            # Save assistant turn
            await self.memory.append_turn(
                input.context.thread_id,
                ConversationTurn(
                    role="assistant",
                    content=output.message,
                    agent_id=self.agent_id,
                    metadata={
                        "is_ready": output.is_ready,
                        "data_types": [dt.value for dt in intent.data_types],
                        "confidence": intent.confidence,
                    },
                ),
            )
        except Exception as exc:
            logger.warning("Failed to persist conversation turn: %s", exc)

    # -- Convenience: build QueryResponse for backward compatibility --------

    def to_query_response(
        self,
        input: AgentInput,
        output: AgentOutput,
    ) -> QueryResponse:
        """Convert AgentOutput to the legacy QueryResponse format."""
        return QueryResponse(
            is_ready=output.is_ready,
            user_message=input.message,
            message=output.message,
            turn_number=0,
            data_types=output.data.get("data_types"),
            date_range=output.data.get("date_range"),
            final_response=output.message if output.is_ready else None,
            clarification_msg=output.message if not output.is_ready else None,
            suggestions=output.suggestions,
            confidence=output.data.get("confidence"),
            trace_id=output.trace_id,
            cost_usd=output.cost_usd,
            latency_ms=output.latency_ms,
        )
