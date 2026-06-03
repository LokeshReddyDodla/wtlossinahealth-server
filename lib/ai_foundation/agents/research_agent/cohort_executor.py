"""
Cohort Executor — runs a CohortSpec.

Pure dispatcher. Looks at ``spec.intent``, calls the right tool, normalizes
the result into an ``ExecutionResult``. No LLM calls, no narration — that's
the responder's job.

The executor also enforces the cohort-resolution rule for ``find`` and
``research`` intents that mention a condition: it expands the cohort via
``find_cohort`` first, then intersects.

Mode 3 (``intent == research``) returns a ``NOT_IMPLEMENTED`` result in
Phase 1 — the Anthropic Batches API wiring it needs lives in the gateway
and is deferred.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from .contracts import (
    CohortIntent,
    CohortSpec,
    ExecutionResult,
    ExecutionResultKind,
    FunnelStep,
)
from .tools import CohortTools

logger = logging.getLogger(__name__)


class CohortExecutor:
    """Run a ``CohortSpec`` against the data layer."""

    def __init__(self, *, tools: CohortTools) -> None:
        self._tools = tools

    async def execute(
        self,
        *,
        spec: CohortSpec,
        cohort_ids: list[str],
        progress: AsyncIterator | None = None,
    ) -> ExecutionResult:
        """Dispatch on ``spec.intent`` and return an ``ExecutionResult``.

        ``cohort_ids`` is the resolved patient panel from the caller.
        The executor may further narrow it via ``find_cohort`` if the
        spec specifies a ``condition`` (e.g. "my piles patients with X").
        """
        start = time.perf_counter()
        result: ExecutionResult

        # Stage 1 — narrow by condition if requested.
        scoped_ids = cohort_ids
        condition_funnel: list[FunnelStep] = []
        find_out: dict[str, Any] | None = None
        if spec.condition:
            find_out = await self._tools.find_cohort(
                condition=spec.condition,
                provider_patient_ids=cohort_ids,
            )
            scoped_ids = list(find_out.get("ids") or [])
            condition_funnel = [
                FunnelStep(step="provider_panel", count=len(cohort_ids)),
                FunnelStep(
                    step=_condition_funnel_label(spec.condition, find_out),
                    count=len(scoped_ids),
                ),
            ]

        # Stage 2 — dispatch on intent.
        if spec.intent == CohortIntent.FIND:
            result = await self._run_find(spec, scoped_ids, cohort_ids, find_out)
        elif spec.intent == CohortIntent.AGGREGATE:
            result = await self._run_aggregate(spec, scoped_ids)
        elif spec.intent == CohortIntent.MATCH:
            result = await self._run_match(spec, scoped_ids)
        elif spec.intent == CohortIntent.MATCH_AND_COUNT:
            result = await self._run_intersect(spec, scoped_ids)
        elif spec.intent == CohortIntent.RANK:
            result = await self._run_rank(spec, scoped_ids)
        elif spec.intent == CohortIntent.RESEARCH:
            result = self._not_implemented_research(spec, scoped_ids)
        else:  # pragma: no cover — exhaustive enum
            result = ExecutionResult(
                kind=ExecutionResultKind.NOT_IMPLEMENTED,
                reason=f"Unknown intent: {spec.intent}",
            )

        # Prepend the condition-narrowing funnel if there was one.
        if condition_funnel:
            result.funnel = condition_funnel + (result.funnel or [])

        # Stage 3 — enrich the final cohort with patient names so the
        # responder can list them by name when the user asks "show me",
        # "list them", "who are they". Capped to keep payloads small.
        if (
            result.kind == ExecutionResultKind.INLINE
            and result.final_ids
            and not result.sample_rows
        ):
            result.sample_rows = await self._tools.resolve_names(result.final_ids)

        result.latency_ms = int((time.perf_counter() - start) * 1000)
        return result

    # ── Intent handlers ────────────────────────────────────────────────

    async def _run_aggregate(
        self,
        spec: CohortSpec,
        cohort_ids: list[str],
    ) -> ExecutionResult:
        # Special metric — survey known condition signatures across the cohort.
        # Doesn't need a per-data-type criterion; the tool iterates the
        # signature table itself.
        if spec.metric == "condition_distribution":
            agg = await self._tools.condition_distribution(cohort_ids=cohort_ids)
            return ExecutionResult(
                kind=ExecutionResultKind.INLINE,
                aggregate_value=agg,
                final_count=int(agg.get("total_patients") or 0),
                path="hybrid",
            )

        if not spec.criteria:
            # Bare "how many patients are in this cohort"
            return ExecutionResult(
                kind=ExecutionResultKind.INLINE,
                aggregate_value={"patient_count": len(cohort_ids)},
                final_count=len(cohort_ids),
                path="mongo",
            )

        criterion = spec.criteria[0]
        agg = await self._tools.cohort_aggregate(
            cohort_ids=cohort_ids,
            data_type=criterion.data_type,
            metric=spec.metric or "count_unique_patients",
            window=criterion.window,
            extra_filter=criterion.filter,
        )
        return ExecutionResult(
            kind=ExecutionResultKind.INLINE,
            aggregate_value=agg,
            final_count=int(agg.get("patient_count") or agg.get("total_records") or 0),
            path="qdrant_fallback",
        )

    async def _run_match(
        self,
        spec: CohortSpec,
        cohort_ids: list[str],
    ) -> ExecutionResult:
        if not spec.criteria:
            return ExecutionResult(
                kind=ExecutionResultKind.INLINE,
                final_ids=cohort_ids,
                final_count=len(cohort_ids),
                path="mongo",
            )
        criterion = spec.criteria[0]
        out = await self._tools.cohort_match(
            cohort_ids=cohort_ids,
            data_type=criterion.data_type,
            window=criterion.window,
            extra_filter=criterion.filter,
        )
        ids = list(out["matched_ids"])
        return ExecutionResult(
            kind=ExecutionResultKind.INLINE,
            final_ids=ids,
            final_count=int(out["count"]),
            funnel=[
                FunnelStep(step="cohort", count=len(cohort_ids)),
                FunnelStep(step=criterion.label or criterion.data_type, count=len(ids)),
            ],
            path="qdrant_fallback",
        )

    async def _run_intersect(
        self,
        spec: CohortSpec,
        cohort_ids: list[str],
    ) -> ExecutionResult:
        return await self._tools.cohort_intersect(
            cohort_ids=cohort_ids,
            criteria=spec.criteria,
            combinator=spec.combinator,
        )

    async def _run_rank(
        self,
        spec: CohortSpec,
        cohort_ids: list[str],
    ) -> ExecutionResult:
        criterion_name = spec.criteria[0].data_type if spec.criteria else (
            spec.metric or "unspecified"
        )
        return await self._tools.rank_cohort(
            cohort_ids=cohort_ids,
            criterion=criterion_name,
            k=spec.k or 20,
        )

    async def _run_find(
        self,
        spec: CohortSpec,
        scoped_ids: list[str],
        original_ids: list[str],
        find_out: dict[str, Any] | None,
    ) -> ExecutionResult:
        # ``find`` is unusual — the cohort narrowing already happened at Stage 1,
        # and Stage 3 (execute()) prepends the condition_funnel rows. So we
        # return an empty funnel here to avoid duplicating those rows, and
        # surface the source breakdown via aggregate_value for the responder.
        aggregate_value = None
        if find_out:
            sources = find_out.get("sources") or {}
            aggregate_value = {
                "by_tag": sources.get("by_tag", 0),
                "by_signature": sources.get("by_signature", 0),
                "by_search": sources.get("by_search", 0),
                "signature_data_types": find_out.get("signature_data_types") or [],
            }
        return ExecutionResult(
            kind=ExecutionResultKind.INLINE,
            final_ids=scoped_ids,
            final_count=len(scoped_ids),
            funnel=[],
            aggregate_value=aggregate_value,
            path="hybrid",
        )

    def _not_implemented_research(
        self,
        spec: CohortSpec,
        cohort_ids: list[str],
    ) -> ExecutionResult:
        return ExecutionResult(
            kind=ExecutionResultKind.NOT_IMPLEMENTED,
            reason=(
                "Cohort Deep Dive (research intent) requires the Anthropic "
                "Batches API and the cohort_worker background job, neither "
                "of which is wired in Phase 1. The provider's question would "
                f"have run a per-patient extraction over {len(cohort_ids)} patients."
            ),
        )


def _condition_funnel_label(condition: str, find_out: dict[str, Any]) -> str:
    """Build a funnel label like ``with_condition:diabetes (38 by data signature,
    5 by tag, 4 by note search)`` so providers can see *why* a patient was
    identified, not just the final count.

    The breakdown comes straight from ``find_cohort``'s ``sources`` dict.
    Empty sources are elided so the label stays terse.
    """
    sources = find_out.get("sources") or {}
    parts: list[str] = []
    by_tag = int(sources.get("by_tag") or 0)
    by_signature = int(sources.get("by_signature") or 0)
    by_search = int(sources.get("by_search") or 0)
    if by_signature:
        parts.append(f"{by_signature} by data signature")
    if by_tag:
        parts.append(f"{by_tag} by tag")
    if by_search:
        parts.append(f"{by_search} by note search")
    suffix = " (" + ", ".join(parts) + ")" if parts else ""
    return f"with_condition:{condition}{suffix}"


__all__ = ["CohortExecutor"]
