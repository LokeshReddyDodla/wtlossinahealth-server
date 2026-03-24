"""
Intent Extraction Evaluator — measures accuracy of intent extraction.

Runs a set of eval cases through the intent extraction pipeline and
scores them on: data_types precision/recall, is_ready accuracy,
date_range accuracy, and confidence calibration.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ..schemas import EvalCase, EvalResult, EvalRunSummary, EvalTaskType
from ..quality import (
    judge_exact_match,
    judge_set_precision,
    judge_set_recall,
)

if TYPE_CHECKING:
    from lib.ai_foundation.models.gateway import ModelGateway
    from lib.ai_foundation.models.registry import ModelTask

logger = logging.getLogger(__name__)


def load_eval_cases(path: Path) -> list[EvalCase]:
    """Load eval cases from a JSONL file."""
    cases: list[EvalCase] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                data = json.loads(line)
                cases.append(EvalCase(**data))
            except Exception as exc:
                logger.warning("Skipping invalid case at line %d: %s", line_num, exc)
    return cases


class IntentEvalRunner:
    """Runs intent extraction evaluation against a set of cases.

    The runner calls the provided ``extract_fn`` for each case and
    compares the output against expected values using deterministic judges.

    Example::

        runner = IntentEvalRunner(
            gateway=gateway,
            system_prompt="Extract health query intent...",
            response_model=QueryIntent,
        )
        summary = await runner.run(cases, model_id="gpt-4.1-mini")
        print(summary.summary_line())
    """

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        system_prompt: str,
        response_model: type[BaseModel],
    ) -> None:
        self._gateway = gateway
        self._system_prompt = system_prompt
        self._response_model = response_model

    async def run(
        self,
        cases: list[EvalCase],
        *,
        model_id: str | None = None,
        prompt_version: str = "",
    ) -> EvalRunSummary:
        """Run all eval cases and produce a summary.

        Args:
            cases: List of eval cases to run.
            model_id: Optional model override.
            prompt_version: Version string for tracking.

        Returns:
            ``EvalRunSummary`` with per-case results and aggregates.
        """
        from lib.ai_foundation.models.registry import ModelTask

        summary = EvalRunSummary(
            task_type=EvalTaskType.INTENT_EXTRACTION,
            model_used=model_id or "default",
            prompt_version=prompt_version,
        )

        for case in cases:
            result = await self._eval_one(case, model_id=model_id)
            result.run_id = summary.run_id
            result.prompt_version = prompt_version
            summary.results.append(result)

        summary.compute_aggregates()
        summary.completed_at = summary.results[-1].evaluated_at if summary.results else None

        logger.info(
            "Intent eval complete: %s",
            summary.summary_line(),
        )
        return summary

    async def _eval_one(
        self,
        case: EvalCase,
        *,
        model_id: str | None = None,
    ) -> EvalResult:
        """Evaluate a single case."""
        from lib.ai_foundation.models.registry import ModelTask

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": case.input_query},
        ]

        # Add conversation context if present
        if case.conversation_context:
            context_msg = {
                "role": "system",
                "content": f"Conversation context: {json.dumps(case.conversation_context)}",
            }
            messages.insert(1, context_msg)

        start = time.perf_counter()
        try:
            parsed, meta = await self._gateway.extract(
                messages=messages,
                response_model=self._response_model,
                task=ModelTask.INTENT_EXTRACTION,
                model_id=model_id,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            actual = parsed.model_dump(mode="json")
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return EvalResult(
                case_id=case.case_id,
                task_type=EvalTaskType.INTENT_EXTRACTION,
                latency_ms=latency_ms,
                model_used=model_id or "default",
                error=str(exc),
            )

        # Run judges
        verdicts = []

        # is_ready accuracy
        if case.expected_is_ready is not None:
            verdicts.append(judge_exact_match(
                "is_ready_accuracy",
                actual.get("is_ready"),
                case.expected_is_ready,
            ))

        # data_types precision & recall
        if case.expected_data_types is not None:
            actual_types = actual.get("data_types", [])
            # Normalize: handle both string and dict representations
            if actual_types and isinstance(actual_types[0], dict):
                actual_types = [t.get("value", t) for t in actual_types]

            verdicts.append(judge_set_precision(
                "data_types_precision",
                actual_types,
                case.expected_data_types,
            ))
            verdicts.append(judge_set_recall(
                "data_types_recall",
                actual_types,
                case.expected_data_types,
            ))

        # Date range accuracy (if expected)
        if case.expected_date_range and actual.get("date_range"):
            actual_range = actual["date_range"]
            expected_range = case.expected_date_range

            start_match = (
                actual_range.get("start", "")[:10] == expected_range.get("start", "")[:10]
                if expected_range.get("start")
                else True
            )
            end_match = (
                actual_range.get("end", "")[:10] == expected_range.get("end", "")[:10]
                if expected_range.get("end")
                else True
            )

            date_score = (int(start_match) + int(end_match)) / 2
            verdicts.append({
                "metric_name": "date_range_accuracy",
                "score": date_score,
                "passed": date_score >= 0.5,
                "threshold": 0.5,
                "details": f"start_match={start_match}, end_match={end_match}",
                "judge_type": "exact",
            })
            # Convert dict to JudgeVerdict
            from ..schemas import JudgeVerdict
            verdicts[-1] = JudgeVerdict(**verdicts[-1])

        all_passed = all(v.passed for v in verdicts) if verdicts else False

        return EvalResult(
            case_id=case.case_id,
            task_type=EvalTaskType.INTENT_EXTRACTION,
            actual_output=actual,
            verdicts=verdicts,
            passed=all_passed,
            latency_ms=latency_ms,
            model_used=model_id or meta.model_id,
        )
