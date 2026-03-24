"""
Response Quality Evaluator — measures quality of final agent responses.

Uses both deterministic judges (keyword presence, forbidden content) and
LLM-as-judge scoring (factual grounding, completeness, tone, safety).
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from ..schemas import EvalCase, EvalResult, EvalRunSummary, EvalTaskType
from ..quality import (
    QualityScorer,
    judge_contains_keywords,
    judge_not_contains,
)

if TYPE_CHECKING:
    from lib.ai_foundation.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


class ResponseEvalRunner:
    """Evaluates the quality of agent responses.

    Combines deterministic checks (keyword presence, forbidden terms)
    with LLM-as-judge scoring for each response.

    Example::

        runner = ResponseEvalRunner(gateway=gateway)
        summary = await runner.run(cases, response_fn=my_agent_fn)
        print(summary.summary_line())
    """

    def __init__(
        self,
        *,
        gateway: ModelGateway | None = None,
        quality_scorer: QualityScorer | None = None,
    ) -> None:
        self._gateway = gateway
        self._scorer = quality_scorer or QualityScorer(gateway)

    async def run(
        self,
        cases: list[EvalCase],
        *,
        response_fn: Any,
        model_id: str | None = None,
        prompt_version: str = "",
    ) -> EvalRunSummary:
        """Run all eval cases and produce a summary.

        Args:
            cases: List of eval cases.
            response_fn: Async callable that takes (query, context) and returns
                a dict with at least ``{"message": str, "retrieved_data": list}``.
            model_id: Model used for tracking.
            prompt_version: Prompt version for tracking.

        Returns:
            ``EvalRunSummary`` with per-case results and aggregates.
        """
        summary = EvalRunSummary(
            task_type=EvalTaskType.RESPONSE_GENERATION,
            model_used=model_id or "default",
            prompt_version=prompt_version,
        )

        for case in cases:
            result = await self._eval_one(case, response_fn=response_fn)
            result.run_id = summary.run_id
            result.prompt_version = prompt_version
            result.model_used = model_id or "default"
            summary.results.append(result)

        summary.compute_aggregates()
        summary.completed_at = summary.results[-1].evaluated_at if summary.results else None

        logger.info("Response eval complete: %s", summary.summary_line())
        return summary

    async def _eval_one(
        self,
        case: EvalCase,
        *,
        response_fn: Any,
    ) -> EvalResult:
        """Evaluate a single response case."""
        start = time.perf_counter()

        try:
            output = await response_fn(
                case.input_query,
                case.conversation_context,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)

            response_text = output.get("message", "")
            retrieved_data = output.get("retrieved_data", [])
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return EvalResult(
                case_id=case.case_id,
                task_type=EvalTaskType.RESPONSE_GENERATION,
                latency_ms=latency_ms,
                error=str(exc),
            )

        verdicts = []

        # Deterministic: keyword presence
        if case.expected_response_contains:
            verdicts.append(judge_contains_keywords(
                "response_contains",
                response_text,
                case.expected_response_contains,
            ))

        # Deterministic: forbidden content
        if case.expected_response_not_contains:
            verdicts.append(judge_not_contains(
                "response_not_contains",
                response_text,
                case.expected_response_not_contains,
            ))

        # LLM-as-judge: quality dimensions
        quality_score = await self._scorer.score_response(
            query=case.input_query,
            response=response_text,
            retrieved_data=retrieved_data,
        )
        quality_verdicts = self._scorer.quality_to_verdicts(quality_score)
        verdicts.extend(quality_verdicts)

        all_passed = all(v.passed for v in verdicts) if verdicts else False

        return EvalResult(
            case_id=case.case_id,
            task_type=EvalTaskType.RESPONSE_GENERATION,
            actual_output={
                "message": response_text[:500],
                "quality_scores": quality_score.model_dump(),
                "overall_quality": quality_score.overall,
            },
            verdicts=verdicts,
            passed=all_passed,
            latency_ms=latency_ms,
        )
