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

# Token budget guards
_MAX_RAW_RECORDS = 20        # detail mode: send raw records up to this count
_MAX_PATIENT_SUMMARIES = 500  # population mode: ~500 rows ≈ 50K tokens, fits in 128K context
_MAX_ANALYSIS_CHARS = 80_000  # hard cap on analysis JSON size (~20K tokens)

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

    def __init__(self, patient_resolver: Any | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._prompts_registered = False
        self._patient_resolver = patient_resolver  # PatientNameResolver (optional)

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
            thread_summary = await self._load_thread_summary(input)
            patient_names = await self._resolve_patient_names(input.context.patient_ids, [])
            self._last_patient_names = patient_names  # shared with _extract_intent for suggestions

            # 2. Extract intent
            intent, intent_meta = await self._extract_intent(input, memory_facts, history, thread_summary)

            # 2b. Extract and persist patient facts (separate LLM call, fire-and-forget)
            await self._extract_and_persist_facts(input)

            # 3. If not ready → clarification
            if not intent.is_ready:
                output = self._build_clarification_output(intent, intent_meta)
                await self._persist_turn(input, output, intent)
                return output

            # 4. Retrieve data
            retrieved = await self._retrieve_data(input, intent)

            # 5. Build analysis
            analysis = await self._build_analysis(intent, retrieved, input.context.patient_ids)

            # 6. Generate response
            response_text = await self._generate_response(input, intent, analysis, memory_facts, history, patient_names)

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
            thread_summary = await self._load_thread_summary(input)
            patient_names = await self._resolve_patient_names(input.context.patient_ids, [])
            self._last_patient_names = patient_names  # shared with _extract_intent for suggestions
            intent, intent_meta = await self._extract_intent(input, memory_facts, history, thread_summary)

            # Extract and persist patient facts (separate LLM call, fire-and-forget)
            await self._extract_and_persist_facts(input)

            yield sse_intent(intent.model_dump(mode="json", exclude_none=True))

            if not intent.is_ready:
                clarification = intent.clarification_msg or "Could you tell me more about what you'd like to know?"
                # Persist BEFORE yielding (yields may be the last thing consumed)
                print(f"[STREAM] not_ready path — persisting clarification turn")
                output = AgentOutput(message=clarification, is_ready=False, trace_id=trace.trace_id if trace else None)
                await self._persist_turn(input, output, intent)

                yield sse_token(clarification)
                yield sse_done(SSEDonePayload(
                    suggestions=[s.model_dump() for s in intent.suggestions],
                    trace_id=trace.trace_id if trace else None,
                    latency_ms=int((time.perf_counter() - pipeline_start) * 1000),
                ))
                return

            # Stage 2: Retrieve
            yield sse_status(PipelineStage.FETCHING_DATA, "Pulling your health data...")

            retrieved = await self._retrieve_data(input, intent)
            analysis = await self._build_analysis(intent, retrieved, input.context.patient_ids)

            # Stage 3: Generate (streaming)
            yield sse_status(PipelineStage.GENERATING_RESPONSE, "Generating response...")

            full_text_parts: list[str] = []
            response_messages = self._build_response_messages(input, intent, analysis, memory_facts, history, patient_names)

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

            # Persist BEFORE yielding done (connection may close after last yield)
            full_text = "".join(full_text_parts)
            print(f"[STREAM] ready path — persisting turn, text_len={len(full_text)}")
            output = AgentOutput(message=full_text, is_ready=True, trace_id=trace.trace_id if trace else None)
            await self._persist_turn(input, output, intent)
            print("[STREAM] persist done")

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

    async def _load_thread_summary(self, input: AgentInput) -> str | None:
        """Load the compacted thread summary if available."""
        if not self.memory or not input.context.thread_id:
            return None
        try:
            summary = await self.memory.get_thread_summary(input.context.thread_id)
            return summary.summary if summary else None
        except Exception as exc:
            logger.warning("Failed to load thread summary: %s", exc)
            return None

    async def _extract_intent(
        self,
        input: AgentInput,
        memory_facts: list[dict],
        history: list[dict[str, str]],
        thread_summary: str | None = None,
    ) -> tuple[QueryIntent, Any]:
        """Extract structured intent from the user's message."""
        self._ensure_prompts()

        system_prompt = self._get_system_prompt(input.context.user_role)
        intent_prompt = self.prompts.get("hq_intent_extraction").body

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": intent_prompt},
        ]

        # Inject thread summary for long conversations
        if thread_summary:
            messages.append({
                "role": "system",
                "content": f"Conversation summary so far:\n{thread_summary}",
            })

        # Inject role context for suggestions
        if input.context.user_role in ("care_provider", "admin"):
            names = []
            if hasattr(self, '_last_patient_names') and self._last_patient_names:
                names = [f"{name}" for pid, name in self._last_patient_names.items()]
            patient_label = ", ".join(names) if names else "the patient(s)"
            messages.append({
                "role": "system",
                "content": (
                    f"IMPORTANT: The user is a {input.context.user_role}, NOT a patient. "
                    f"They are asking about: {patient_label}. "
                    f"In suggestions and clarification messages, refer to patients by name. "
                    f"NEVER use 'my' or 'your' — use the patient's name or 'the patient'. "
                    f"Example: 'Show Ahmed's glucose today' NOT 'Show my glucose today'."
                ),
            })

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

        payloads = [item.payload for item in result.items]
        print(f"[RETRIEVAL] {len(result.items)} items from sources={result.executed_sources}, degraded={result.degraded_sources}")
        for item in result.items[:5]:
            print(f"  [{item.source}] data_type={item.data_type}, keys={list(item.payload.keys())[:8]}")
        return payloads

    async def _build_analysis(
        self,
        intent: QueryIntent,
        retrieved: list[dict[str, Any]],
        patient_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build a structured analysis snapshot from retrieved data.

        Handles three scenarios:
        1. Single patient, few records → send raw records (detail mode)
        2. Single patient, many records → aggregate by data_type (summary mode)
        3. Multi-patient → aggregate per-patient summaries (population mode)

        For multi-patient, resolves patient UUIDs to names so the LLM
        can respond naturally ("Ahmed had 3 hypos" not "7538e5a0 had 3 hypos").

        Enforces a token budget so the LLM context window is never exceeded.
        """
        domains = list({
            _DATA_TYPE_DOMAINS.get(dt.value, DomainName.CGM).value
            for dt in intent.data_types
        })

        num_patients = len(set(
            item.get("patient_id", "unknown") for item in retrieved
        )) if retrieved else (len(patient_ids) if patient_ids else 1)

        is_multi_patient = num_patients > 1 or (patient_ids and len(patient_ids) > 1)

        if is_multi_patient:
            name_map = await self._resolve_patient_names(patient_ids, retrieved)
            print(f"[ANALYSIS] mode=population, patients={num_patients}, records={len(retrieved)}")
            return self._build_population_analysis(domains, retrieved, patient_ids, name_map)
        elif len(retrieved) > _MAX_RAW_RECORDS:
            print(f"[ANALYSIS] mode=summary, records={len(retrieved)}")
            return self._build_summary_analysis(domains, retrieved)
        else:
            print(f"[ANALYSIS] mode=detail, records={len(retrieved)}")
            return self._build_detail_analysis(domains, retrieved)

    @staticmethod
    def _build_detail_analysis(
        domains: list[str],
        retrieved: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Single patient, few records — format data readably for the LLM.

        No hardcoded field names. Groups by data_type, strips internal
        fields (source, data_type), and presents each record as clean
        key-value text. The LLM interprets the values.
        """
        by_type: dict[str, list[dict]] = {}
        for item in retrieved:
            dt = item.get("data_type", "unknown")
            by_type.setdefault(dt, []).append(item)

        sections: list[str] = []
        for dt, items in by_type.items():
            label = dt.replace("_", " ").upper()
            lines = []
            for item in items:
                # Strip internal fields, keep everything else
                clean = {
                    k: v for k, v in item.items()
                    if k not in ("data_type", "source", "patient_id") and v is not None
                }
                # Flatten one level of nesting for readability
                flat_parts = []
                for k, v in clean.items():
                    if isinstance(v, dict):
                        inner = ", ".join(f"{ik}: {iv}" for ik, iv in v.items() if iv is not None)
                        if inner:
                            flat_parts.append(f"{k}: ({inner})")
                    else:
                        flat_parts.append(f"{k}: {v}")
                lines.append("  - " + ", ".join(flat_parts))

            sections.append(f"{label} ({len(items)} entries):\n" + "\n".join(lines))

        readable_text = "\n\n".join(sections) if sections else "No health data found for this query."

        return {
            "mode": "detail",
            "domains": domains,
            "record_count": len(retrieved),
            "readable_summary": readable_text,
        }

    @staticmethod
    def _build_summary_analysis(
        domains: list[str],
        retrieved: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Single patient, many records — show first 5 per type + count.

        No hardcoded field names. Uses the same generic formatting as detail
        mode but caps at 5 records per type and shows the total count.
        """
        by_type: dict[str, list[dict]] = {}
        for item in retrieved:
            dt = item.get("data_type", "unknown")
            by_type.setdefault(dt, []).append(item)

        sections: list[str] = []
        for dt, items in by_type.items():
            label = dt.replace("_", " ").upper()
            lines = []
            for item in items[:5]:  # show first 5
                clean = {
                    k: v for k, v in item.items()
                    if k not in ("data_type", "source", "patient_id") and v is not None
                }
                flat_parts = []
                for k, v in clean.items():
                    if isinstance(v, dict):
                        inner = ", ".join(f"{ik}: {iv}" for ik, iv in v.items() if iv is not None)
                        if inner:
                            flat_parts.append(f"{k}: ({inner})")
                    else:
                        flat_parts.append(f"{k}: {v}")
                lines.append("  - " + ", ".join(flat_parts))

            if len(items) > 5:
                lines.append(f"  ... and {len(items) - 5} more")

            sections.append(f"{label} ({len(items)} total):\n" + "\n".join(lines))

        readable_text = "\n\n".join(sections) if sections else "No health data found."

        return {
            "mode": "summary",
            "domains": domains,
            "record_count": len(retrieved),
            "readable_summary": readable_text,
        }

    @staticmethod
    def _build_population_analysis(
        domains: list[str],
        retrieved: list[dict[str, Any]],
        patient_ids: list[str] | None = None,
        name_map: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Multi-patient — aggregate per-patient, then produce population summary.

        Instead of sending thousands of records, sends one summary row per patient.
        Patient UUIDs are replaced with display names when available.
        """
        name_map = name_map or {}

        # Group by patient
        by_patient: dict[str, list[dict]] = {}
        for item in retrieved:
            pid = item.get("patient_id", "unknown")
            by_patient.setdefault(pid, []).append(item)

        # Also track patients with no data
        all_pids = set(patient_ids or [])
        pids_with_data = set(by_patient.keys())
        pids_no_data = all_pids - pids_with_data

        # Per-patient summaries
        patient_summaries: list[dict[str, Any]] = []
        for pid, items in by_patient.items():
            display_name = name_map.get(pid, pid[:8])
            ps: dict[str, Any] = {"patient_id": pid, "name": display_name, "record_count": len(items)}

            # CGM
            glucose_vals = [
                i.get("average_glucose_mgdl") or i.get("average_glucose")
                for i in items if "cgm" in (i.get("data_type") or "")
            ]
            glucose_vals = [v for v in glucose_vals if v is not None]
            if glucose_vals:
                ps["avg_glucose"] = round(sum(glucose_vals) / len(glucose_vals), 1)

            tir_vals = [
                i.get("in_target_70_180_percent")
                for i in items if "cgm" in (i.get("data_type") or "")
            ]
            tir_vals = [v for v in tir_vals if v is not None]
            if tir_vals:
                ps["avg_tir_pct"] = round(sum(tir_vals) / len(tir_vals), 1)

            # Meals
            meal_items = [i for i in items if i.get("data_type") == "meal"]
            if meal_items:
                ps["meal_count"] = len(meal_items)

            # Fitness
            steps = [
                i.get("steps") for i in items
                if "fitness" in (i.get("data_type") or "") and i.get("steps") is not None
            ]
            if steps:
                ps["avg_steps"] = round(sum(steps) / len(steps))

            # Hypo events
            hypo_items = [i for i in items if "hypo" in (i.get("data_type") or "")]
            if hypo_items:
                ps["hypo_event_count"] = len(hypo_items)

            patient_summaries.append(ps)

        # Sort by most concerning first (lowest TIR, most hypos)
        patient_summaries.sort(
            key=lambda p: (p.get("avg_tir_pct", 100), -p.get("hypo_event_count", 0)),
        )

        # Population-level aggregates
        population: dict[str, Any] = {
            "total_patients": len(all_pids) or len(by_patient),
            "patients_with_data": len(pids_with_data),
            "patients_no_data": len(pids_no_data),
            "total_records": len(retrieved),
        }

        all_glucose = [p["avg_glucose"] for p in patient_summaries if "avg_glucose" in p]
        if all_glucose:
            population["population_avg_glucose"] = round(sum(all_glucose) / len(all_glucose), 1)

        all_tir = [p["avg_tir_pct"] for p in patient_summaries if "avg_tir_pct" in p]
        if all_tir:
            population["population_avg_tir_pct"] = round(sum(all_tir) / len(all_tir), 1)
            population["patients_below_50_tir"] = sum(1 for t in all_tir if t < 50)
            population["patients_above_70_tir"] = sum(1 for t in all_tir if t >= 70)

        # Highlights
        highlights = [
            f"Population: {population['total_patients']} patients, {len(retrieved)} records",
        ]
        if population.get("population_avg_glucose"):
            highlights.append(f"Avg glucose: {population['population_avg_glucose']} mg/dL")
        if population.get("patients_below_50_tir"):
            highlights.append(f"{population['patients_below_50_tir']} patients with TIR < 50% (need attention)")
        if pids_no_data:
            highlights.append(f"{len(pids_no_data)} patients with no data in this period")

        # Build readable text for the LLM
        lines = []
        for ps in patient_summaries[:_MAX_PATIENT_SUMMARIES]:
            name = ps.get("name", ps.get("patient_id", "Unknown")[:8])
            # Show all metrics without hardcoding which ones exist
            skip_keys = {"patient_id", "name", "record_count"}
            parts = [
                f"{k.replace('_', ' ')}: {v}"
                for k, v in ps.items()
                if k not in skip_keys and v is not None
            ]
            detail = ", ".join(parts) if parts else f"{ps.get('record_count', 0)} records"
            lines.append(f"  - {name}: {detail}")

        readable_text = "\n".join(highlights) + "\n\nPer patient:\n" + "\n".join(lines)

        if pids_no_data:
            readable_text += f"\n\n{len(pids_no_data)} patient(s) have no data in this period."

        return {
            "mode": "population",
            "domains": domains,
            "record_count": len(retrieved),
            "readable_summary": readable_text,
        }

    async def _generate_response(
        self,
        input: AgentInput,
        intent: QueryIntent,
        analysis: dict[str, Any],
        memory_facts: list[dict],
        history: list[dict[str, str]],
        patient_names: dict[str, str] | None = None,
    ) -> str:
        """Generate the final conversational response."""
        messages = self._build_response_messages(input, intent, analysis, memory_facts, history, patient_names)

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
        patient_names: dict[str, str] | None = None,
    ) -> list[dict[str, str]]:
        """Assemble the message list for response generation."""
        self._ensure_prompts()

        system_prompt = self._get_system_prompt(input.context.user_role)
        response_prompt = self.prompts.get("hq_response_generation").body

        # Prefer readable_summary (human text) over raw JSON
        if "readable_summary" in analysis:
            analysis_text = analysis["readable_summary"]
        else:
            analysis_text = json.dumps(analysis, default=str)

        # Hard cap
        if len(analysis_text) > _MAX_ANALYSIS_CHARS:
            analysis_text = analysis_text[:_MAX_ANALYSIS_CHARS] + "\n... (truncated)"

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": response_prompt},
            {"role": "system", "content": f"Health data for this query:\n\n{analysis_text}"},
        ]

        # Inject patient names so the LLM uses real names instead of UUIDs
        if patient_names:
            name_lines = [f"- {pid}: {name}" for pid, name in patient_names.items() if name]
            if name_lines:
                messages.append({
                    "role": "system",
                    "content": (
                        "Patient name mapping (ALWAYS use these names, never UUIDs):\n"
                        + "\n".join(name_lines)
                    ),
                })

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

    async def _resolve_patient_names(
        self,
        patient_ids: list[str] | None,
        retrieved: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Resolve patient UUIDs to display names for natural LLM responses."""
        # Collect all patient IDs from both the request and the data
        all_pids = set(patient_ids or [])
        for item in retrieved:
            pid = item.get("patient_id")
            if pid:
                all_pids.add(pid)

        if not all_pids:
            return {}

        if self._patient_resolver:
            try:
                return await self._patient_resolver.resolve_names(list(all_pids))
            except Exception as exc:
                logger.warning("Patient name resolution failed: %s", exc)

        # Fallback: readable identifiers
        return {pid: f"Patient ({pid[:8]})" for pid in all_pids}

    def _ensure_prompts(self) -> None:
        """Register prompts on first use."""
        if self._prompts_registered or not self.prompts:
            return
        if "hq_system_patient" not in self.prompts:
            self.prompts.register_directory(_PROMPTS_DIR, namespace="health_query")
        self._prompts_registered = True

    def _get_system_prompt(self, user_role: str) -> str:
        """Get the role-appropriate system prompt."""
        role_prompt_map = {
            "admin": "hq_system_admin",
            "care_provider": "hq_system_care_provider",
            "patient": "hq_system_patient",
        }
        name = role_prompt_map.get(user_role, "hq_system_patient")
        logger.debug("System prompt: user_role=%s → prompt=%s", user_role, name)
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

    async def _extract_and_persist_facts(self, input: AgentInput) -> None:
        """Dedicated LLM call to extract patient facts, then persist them.

        Runs as a separate call from intent extraction because small models
        tend to leave optional list fields empty when the main task is complex.
        A focused call with a tiny schema forces the model to actually extract.
        """
        if not self.memory:
            return

        patient_id = input.context.patient_id
        if not patient_id:
            return

        from .contracts import ExtractedFacts

        try:
            result, _ = await self.gateway.extract(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract ALL durable patient facts from the user's message. "
                            "Facts include: goals, weight, dietary preferences, allergies, "
                            "body notes, medical conditions, medications, fasting context, "
                            "activity preferences, communication style. "
                            "Set has_facts=true if ANY facts are found, false otherwise. "
                            "Only extract what is EXPLICITLY stated. Do not infer."
                        ),
                    },
                    {"role": "user", "content": input.message},
                ],
                response_model=ExtractedFacts,
                task=ModelTask.CLASSIFICATION,
            )

            logger.debug(
                "Fact extraction: has_facts=%s, count=%d",
                result.has_facts, len(result.facts),
            )

            if not result.has_facts or not result.facts:
                return

            from lib.ai_foundation.memory.base import MemoryFact

            memory_facts = [
                MemoryFact(
                    key=f.key.strip(),
                    value=f.value.strip(),
                    source="user",
                    agent_id=self.agent_id,
                    confidence=1.0,
                )
                for f in result.facts
                if f.key.strip() and f.value.strip()
            ]

            if memory_facts:
                await self.memory.upsert_patient_facts(patient_id, memory_facts)
                logger.debug("Persisted %d facts for patient", len(memory_facts))

        except Exception as exc:
            logger.warning("Fact extraction failed (non-blocking): %s", exc)

    async def _persist_turn(
        self,
        input: AgentInput,
        output: AgentOutput,
        intent: QueryIntent,
    ) -> None:
        """Save conversation turns to the shared memory store."""
        print(f"[PERSIST_TURN] called. memory={self.memory is not None}, thread_id={input.context.thread_id}")
        if not self.memory:
            print("[PERSIST_TURN] SKIP: no memory store")
            return
        if not input.context.thread_id:
            print("[PERSIST_TURN] SKIP: no thread_id")
            return

        print(f"[PERSIST_TURN] saving to thread={input.context.thread_id}")

        from lib.ai_foundation.memory.base import ConversationTurn

        try:
            # Save user turn
            print(f"[PERSIST_TURN] appending user turn: {input.message[:50]}...")
            await self.memory.append_turn(
                input.context.thread_id,
                ConversationTurn(
                    role="user",
                    content=input.message,
                    agent_id=self.agent_id,
                ),
            )
            print("[PERSIST_TURN] user turn saved")
            # Save assistant turn
            print(f"[PERSIST_TURN] appending assistant turn: {output.message[:50]}...")
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

            # Compact thread every 4 turns
            await self._maybe_compact_thread(input)

            # Record implicit feedback signals
            await self._record_implicit_signals(input, intent)

            print("[PERSIST_TURN] all done — both turns saved + compaction checked")
        except Exception as exc:
            print(f"[PERSIST_TURN] FAILED: {exc}")
            logger.warning("Failed to persist conversation turn: %s", exc)

    async def _record_implicit_signals(
        self, input: AgentInput, intent: QueryIntent,
    ) -> None:
        """Detect and record implicit quality signals for training data.

        If the previous assistant response said is_ready=True but the user
        is now clarifying (is_ready=False on this turn), that means the
        previous intent extraction was wrong — record as negative signal.
        """
        if not self.memory or not input.context.thread_id:
            return

        try:
            turns = await self.memory.get_thread_turns(input.context.thread_id, limit=4)
            if len(turns) < 3:
                return

            # Find the previous assistant turn
            prev_assistant = None
            for t in reversed(turns[:-2]):  # skip the 2 we just added
                if t.role == "assistant":
                    prev_assistant = t
                    break

            if not prev_assistant or not prev_assistant.metadata:
                return

            prev_was_ready = prev_assistant.metadata.get("is_ready", False)
            prev_trace_id = prev_assistant.metadata.get("trace_id")

            if prev_was_ready and not intent.is_ready:
                # User clarifying after we said is_ready=True → intent was wrong
                logger.info(
                    "Implicit negative signal: user clarified after is_ready=True (trace=%s)",
                    prev_trace_id,
                )
                from lib.ai_foundation.eval.collector import FinetuneDataCollector
                from lib.core.container import container
                try:
                    collector: FinetuneDataCollector = container.resolve(FinetuneDataCollector)
                    if prev_trace_id:
                        await collector.add_implicit_signal(
                            prev_trace_id, "user_asked_clarification_after", True,
                        )
                except Exception as inner_exc:
                    logger.debug("Implicit signal recording failed: %s", inner_exc)

        except Exception as exc:
            logger.debug("Implicit signal detection failed: %s", exc)

    async def _maybe_compact_thread(self, input: AgentInput) -> None:
        """Summarize the conversation thread and generate a title.

        - Title: generated on turn 2 (first complete exchange), kept forever
        - Summary: generated at turn 4+, updated every 2 turns
        """
        if not self.memory or not input.context.thread_id:
            return

        try:
            turns = await self.memory.get_thread_turns(input.context.thread_id, limit=30)
            turn_count = len(turns)

            existing = await self.memory.get_thread_summary(input.context.thread_id)

            # Generate title on turn 2 (first user+assistant pair)
            if turn_count >= 2 and (not existing or not existing.title):
                title = await self._generate_thread_title(turns[:2])
                from lib.ai_foundation.memory.base import ThreadSummary
                summary = existing or ThreadSummary(
                    thread_id=input.context.thread_id,
                    summary="",
                    turn_count=turn_count,
                )
                summary.title = title
                summary.turn_count = turn_count
                await self.memory.save_thread_summary(input.context.thread_id, summary)
                existing = summary

            # Only compact summary after 4+ turns, and every 2 turns after that
            if turn_count < 4 or turn_count % 2 != 0:
                return

            if existing and existing.turn_count >= turn_count - 1:
                return  # already summarized recently

            # Build conversation text for summarization
            conv_lines = []
            for t in turns[-12:]:  # last 12 turns max
                conv_lines.append(f"{t.role}: {t.content[:200]}")
            conv_text = "\n".join(conv_lines)

            from .contracts import DomainName
            from lib.ai_foundation.memory.base import ThreadSummary

            # Use a cheap LLM call to summarize
            response = await self.gateway.complete(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Summarize this health conversation in 2-3 sentences. "
                            "Include: what health topics were discussed, what time period, "
                            "any patient goals mentioned, and the current state of the conversation. "
                            "Be concise."
                        ),
                    },
                    {"role": "user", "content": conv_text},
                ],
                task=ModelTask.SUMMARIZATION,
            )

            # Extract domains from turn metadata
            domains = set()
            for t in turns:
                for dt in t.metadata.get("data_types", []):
                    domain = _DATA_TYPE_DOMAINS.get(dt)
                    if domain:
                        domains.add(domain.value)

            # Preserve existing title
            title = existing.title if existing and existing.title else ""

            summary = ThreadSummary(
                thread_id=input.context.thread_id,
                title=title,
                summary=response.content,
                domains=list(domains),
                turn_count=turn_count,
            )
            await self.memory.save_thread_summary(input.context.thread_id, summary)
            logger.info(
                "Compacted thread %s (%d turns): %s",
                input.context.thread_id, turn_count, response.content[:100],
            )

        except Exception as exc:
            logger.warning("Thread compaction failed (non-blocking): %s", exc)

    async def _generate_thread_title(self, first_turns: list) -> str:
        """Generate a short title from the first user message, like ChatGPT does.

        Returns a 3-8 word title. Uses the cheap classification model.
        """
        first_user_msg = ""
        for t in first_turns:
            if t.role == "user":
                first_user_msg = t.content
                break

        if not first_user_msg:
            return "New conversation"

        try:
            response = await self.gateway.complete(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Generate a short title (3-8 words) for a health conversation "
                            "that starts with this message. The title should be descriptive "
                            "and human-readable, like a chat title. "
                            "Return ONLY the title, nothing else. No quotes, no punctuation at the end."
                        ),
                    },
                    {"role": "user", "content": first_user_msg},
                ],
                task=ModelTask.CLASSIFICATION,
            )
            title = response.content.strip().strip('"').strip("'")
            # Cap at 60 chars
            if len(title) > 60:
                title = title[:57] + "..."
            logger.debug("Generated thread title: %s", title)
            return title
        except Exception as exc:
            logger.warning("Title generation failed: %s", exc)
            # Fallback: first 50 chars of the message
            return first_user_msg[:50] + ("..." if len(first_user_msg) > 50 else "")

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
