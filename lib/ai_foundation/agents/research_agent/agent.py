"""
ResearchAgent — public entrypoint.

Mirrors the shape of ``health_query.HealthQueryAgent`` so it integrates
cleanly with the foundation: same ``BaseAgent`` parent, same
``AgentInput``/``AgentOutput`` surface via the convenience wrappers,
same SSE event format. The internal pipeline is plan → execute → respond,
not the open-ended reasoning loop the chat agent uses.

Construction (in the DI container):

    container.register(
        ResearchAgent,
        lambda: ResearchAgent(
            gateway=container.resolve(ModelGateway),
            mongo_store=container.resolve(MongoStore),
            qdrant_store=container.resolve(QdrantStore),
            memory=container.resolve(MongoMemoryStore),
            prompts=container.resolve(PromptRegistry),
            event_bus=container.resolve(EventBus),
        ),
        scope=Scope.singleton,
    )

Public surface:

    agent.run(input: ResearchInput) -> ResearchOutput              # one-shot
    agent.run_stream(input: ResearchInput) -> AsyncIterator[str]   # SSE events
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, AsyncIterator

from lib.ai_foundation.agents.base import BaseAgent
from lib.ai_foundation.config import settings
from lib.ai_foundation.streaming.sse import (
    PipelineStage,
    SSEDonePayload,
    sse_done,
    sse_error,
    sse_event,
    sse_intent,
    sse_status,
    sse_token,
    sse_tool_call,
    sse_tool_result,
)

from .cohort_executor import CohortExecutor
from .cohort_planner import CohortPlanner
from .contracts import (
    CohortRef,
    CohortRefKind,
    ResearchInput,
    ResearchOutput,
)
from .reasoning_engine import ResearchReasoning
from .tools import CohortTools

logger = logging.getLogger(__name__)


class ResearchAgent(BaseAgent):
    """Cohort-scale research agent.

    Phase 1 modes supported:
      - Mode 1 (Cohort Insights): aggregate, find, match
      - Mode 2 (Cohort Brief): match_and_count (multi-criterion intersection)

    Phase 1 modes deferred:
      - Mode 3 (Cohort Deep Dive): research intent → NOT_IMPLEMENTED until
        Anthropic Batches + cohort_worker ship
      - rank intent → NOT_IMPLEMENTED until the scorecard scan ships
    """

    agent_id = "research_v1"

    def __init__(
        self,
        *,
        gateway: Any,
        mongo_store: Any,
        qdrant_store: Any,
        memory: Any = None,
        prompts: Any = None,
        event_bus: Any = None,
        embed_fn: Any = None,
        patient_name_resolver: Any = None,
        health_query_agent: Any = None,
        qdrant_collection: str = "patient_data",
    ) -> None:
        super().__init__(
            gateway=gateway,
            memory=memory,
            prompts=prompts,
            event_bus=event_bus,
        )
        self._mongo_store = mongo_store
        self._qdrant_store = qdrant_store
        self._embed_fn = embed_fn
        self._patient_name_resolver = patient_name_resolver
        self._health_query_agent = health_query_agent
        self._qdrant_collection = qdrant_collection

        self._planner = CohortPlanner(
            gateway=gateway,
            timeout_seconds=getattr(settings, "PLANNING_TIMEOUT_SECONDS", 15.0),
        )
        self._reasoning = ResearchReasoning(
            gateway=gateway,
            timeout_seconds=getattr(settings, "REASONING_TIMEOUT_SECONDS", 30.0),
        )

    # ── Tool construction ─────────────────────────────────────────────

    def _build_tools(self) -> CohortTools:
        return CohortTools(
            qdrant_store=self._qdrant_store,
            mongo_store=self._mongo_store,
            qdrant_collection=self._qdrant_collection,
            embed_fn=self._embed_fn,
            patient_name_resolver=self._patient_name_resolver,
            health_query_agent=self._health_query_agent,
        )

    # ── Public API ─────────────────────────────────────────────────────

    async def run(self, input: ResearchInput) -> ResearchOutput:  # type: ignore[override]
        """One-shot, non-streaming execution.

        Override of ``BaseAgent.run``'s signature: this agent uses its own
        ``ResearchInput`` / ``ResearchOutput`` shapes rather than the
        foundation-wide ``AgentInput`` / ``AgentOutput``. Callers that want
        the standard interface can use the small wrapper at
        ``ResearchAgent.run_with_agent_input``.
        """
        start = time.perf_counter()
        trace_id = input.trace_id or str(uuid.uuid4())
        self.gateway.langfuse_trace_input(
            trace_id=trace_id, name="research", input_text=input.question,
        )

        cohort_ids = await self._resolve_cohort(input.cohort)

        spec, planner_meta = await self._planner.plan(
            question=input.question,
            cohort_size_hint=len(cohort_ids),
            history=input.history,
            trace_id=trace_id,
        )

        tools = self._build_tools()
        executor = CohortExecutor(tools=tools)
        result = await executor.execute(spec=spec, cohort_ids=cohort_ids)

        answer, responder_meta = await self._reasoning.respond(
            question=input.question,
            spec=spec,
            result=result,
            planner_meta=planner_meta,
            history=input.history,
            trace_id=trace_id,
        )

        total_cost = (planner_meta.get("cost_usd") or 0.0) + (
            responder_meta.get("cost_usd") or 0.0
        )
        total_latency_ms = int((time.perf_counter() - start) * 1000)
        self.gateway.langfuse_trace_output(trace_id=trace_id, output_text=answer or "")

        return ResearchOutput(
            answer=answer,
            spec=spec,
            execution=result,
            suggestions=[],
            cost_usd=total_cost,
            latency_ms=total_latency_ms,
            model_id=responder_meta.get("model_id"),
            trace_id=trace_id,
            audit_id=None,  # Phase 4: write to ai_cohort_audit and return ID.
        )

    async def run_stream(  # type: ignore[override]
        self,
        input: ResearchInput,
    ) -> AsyncIterator[str]:
        """SSE streaming execution.

        Emits the standard foundation event types so existing clients work
        out of the box:

            status        → planning / executing / responding stages
            intent        → the parsed CohortSpec (mapped from `intent`)
            tool_call     → cohort_aggregate / cohort_match / cohort_intersect
            tool_result   → funnel rows + final count summary
            token         → responder narration tokens
            done          → trace_id, cost, latency, audit_id
            error         → on failure
        """
        start = time.perf_counter()
        trace_id = input.trace_id or str(uuid.uuid4())
        self.gateway.langfuse_trace_input(
            trace_id=trace_id, name="research", input_text=input.question,
        )

        try:
            yield sse_status(PipelineStage.UNDERSTANDING_QUERY)

            cohort_ids = await self._resolve_cohort(input.cohort)

            yield sse_status(
                PipelineStage.EXTRACTING_INTENT,
                message=f"Planning across {len(cohort_ids)} patients",
            )

            spec, planner_meta = await self._planner.plan(
                question=input.question,
                cohort_size_hint=len(cohort_ids),
                history=input.history,
                trace_id=trace_id,
            )
            yield sse_intent({
                "intent": spec.intent.value,
                "criteria_count": len(spec.criteria),
                "combinator": spec.combinator.value,
                "output": spec.output.value,
                "fallback": bool(planner_meta.get("fallback")),
            })

            yield sse_status(PipelineStage.FETCHING_DATA)
            yield sse_tool_call(
                tool=f"cohort_{spec.intent.value}",
                args={
                    "criteria": [c.model_dump() for c in spec.criteria],
                    "cohort_size": len(cohort_ids),
                    "condition": spec.condition,
                },
                reason=f"intent={spec.intent.value}",
            )

            tools = self._build_tools()
            executor = CohortExecutor(tools=tools)
            result = await executor.execute(spec=spec, cohort_ids=cohort_ids)

            # Emit funnel as a single tool_result summary.
            funnel_summary = " → ".join(
                f"{step.step}={step.count}" for step in (result.funnel or [])
            ) or f"final={result.final_count}"
            yield sse_tool_result(
                tool=f"cohort_{spec.intent.value}",
                summary=funnel_summary,
            )

            # Custom per-patient progress event for future Phase 2 use; harmless now.
            for step in result.funnel or []:
                yield sse_event(
                    "funnel_step",
                    {"step": step.step, "count": step.count},
                )

            yield sse_status(PipelineStage.GENERATING_RESPONSE)
            answer, responder_meta = await self._reasoning.respond(
                question=input.question,
                spec=spec,
                result=result,
                planner_meta=planner_meta,
                history=input.history,
                trace_id=trace_id,
            )

            # Stream the answer as tokens. The gateway exposes a real token
            # stream via .stream(), but the responder here uses .complete()
            # for simplicity in Phase 1 — we emit the full answer as one token
            # event. Phase 2 swaps in .stream() for true token-by-token.
            yield sse_token(answer)

            total_cost = (planner_meta.get("cost_usd") or 0.0) + (
                responder_meta.get("cost_usd") or 0.0
            )
            total_latency_ms = int((time.perf_counter() - start) * 1000)

            yield sse_done(SSEDonePayload(
                trace_id=trace_id,
                cost_usd=total_cost,
                latency_ms=total_latency_ms,
                model_id=responder_meta.get("model_id"),
                suggestions=[],
                data={
                    "intent": spec.intent.value,
                    "final_count": result.final_count,
                    "path": result.path,
                    "execution_kind": result.kind.value,
                },
            ))
        except Exception as exc:
            logger.exception("ResearchAgent stream failed: %s", exc)
            yield sse_error(
                message="The research agent hit an error processing this question.",
                code="research_agent_error",
                fallback_text=str(exc),
            )

    # ── Cohort resolution ─────────────────────────────────────────────

    async def _resolve_cohort(self, cohort: CohortRef) -> list[str]:
        """Translate a ``CohortRef`` into a concrete list of patient IDs.

        Phase 1:
          - IDS: returned as-is (caller responsible for access checks at the
                 REST layer; the agent trusts the list).
          - SAVED: NotImplementedError — needs ``ai_cohorts`` collection (Phase 2).
          - PANEL: NotImplementedError — needs
                  ``CareProviderAccessService.get_all_assigned_patients`` (deferred decision).

        The REST endpoint must enforce access control BEFORE calling the agent.
        This method does not call PostgreSQL, by design.
        """
        if cohort.kind == CohortRefKind.IDS:
            return list(cohort.ids or [])

        if cohort.kind == CohortRefKind.SAVED:
            raise NotImplementedError(
                "Saved cohorts require the ai_cohorts collection — Phase 2. "
                "Pass explicit patient IDs via cohort.kind='ids' for now."
            )

        if cohort.kind == CohortRefKind.PANEL:
            raise NotImplementedError(
                "Whole-panel cohorts require CareProviderAccessService."
                "get_all_assigned_patients() — pending decision in Phase 1 (see "
                "research_agent_plan.md 'Decisions to lock'). Pass explicit "
                "patient IDs via cohort.kind='ids' for now."
            )

        raise ValueError(f"Unsupported CohortRefKind: {cohort.kind}")


__all__ = ["ResearchAgent"]
