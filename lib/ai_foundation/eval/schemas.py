"""
Evaluation Schemas — data models for eval cases, results, and run summaries.

Eval cases are authored as JSONL files and loaded by eval runners.
Results capture per-case verdicts and aggregate into run summaries
for comparing prompt versions, model changes, or fine-tuned models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EvalTaskType(str, Enum):
    """What layer of the pipeline is being evaluated."""

    INTENT_EXTRACTION = "intent_extraction"
    RETRIEVAL = "retrieval"
    RESPONSE_GENERATION = "response_generation"
    END_TO_END = "end_to_end"


class EvalCase(BaseModel):
    """A single test case for evaluation.

    Cases are typically stored as JSONL and loaded by eval runners.
    """

    case_id: str = Field(description="Unique case identifier, e.g. 'intent-001'.")
    task_type: EvalTaskType
    input_query: str = Field(description="The user's message to evaluate against.")
    conversation_context: dict[str, Any] | None = Field(
        default=None,
        description="Optional prior conversation context.",
    )
    user_role: str = "patient"
    patient_id: str | None = None

    # Expected outputs (ground truth)
    expected_intent: dict[str, Any] | None = Field(
        default=None,
        description="Full expected QueryIntent for intent eval.",
    )
    expected_data_types: list[str] | None = Field(
        default=None,
        description="Expected data_types subset for intent eval.",
    )
    expected_is_ready: bool | None = Field(
        default=None,
        description="Expected is_ready value.",
    )
    expected_date_range: dict[str, str] | None = Field(
        default=None,
        description="Expected date range {start, end} for temporal accuracy.",
    )
    expected_response_contains: list[str] | None = Field(
        default=None,
        description="Keywords the response must contain.",
    )
    expected_response_not_contains: list[str] | None = Field(
        default=None,
        description="Keywords the response must NOT contain (hallucination check).",
    )

    tags: list[str] = Field(
        default_factory=list,
        description="Tags for filtering: ['cgm', 'follow_up', 'date_range', etc.].",
    )
    source: str = Field(
        default="manual",
        description="How this case was created: 'manual', 'production', 'synthetic'.",
    )
    difficulty: str = Field(
        default="normal",
        description="Difficulty level: 'easy', 'normal', 'hard'.",
    )


class JudgeVerdict(BaseModel):
    """Output from a single judge on a single case."""

    metric_name: str = Field(description="E.g. 'data_types_precision', 'response_coherence'.")
    score: float = Field(ge=0.0, le=1.0, description="Score from 0.0 to 1.0.")
    passed: bool = Field(description="Whether this metric passes the threshold.")
    threshold: float = Field(default=0.8, description="The pass/fail threshold.")
    details: str | None = Field(default=None, description="Explanation for the score.")
    judge_type: str = Field(
        default="exact",
        description="How the verdict was produced: 'exact', 'fuzzy', 'llm'.",
    )


class EvalResult(BaseModel):
    """Result of evaluating a single case."""

    model_config = {"protected_namespaces": ()}

    case_id: str
    task_type: EvalTaskType
    actual_output: dict[str, Any] = Field(
        default_factory=dict,
        description="The model's actual output for this case.",
    )
    verdicts: list[JudgeVerdict] = Field(default_factory=list)
    passed: bool = Field(
        default=False,
        description="True if ALL verdicts passed.",
    )
    latency_ms: int = 0
    model_used: str = ""
    prompt_version: str = ""
    run_id: str = ""
    error: str | None = None
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def avg_score(self) -> float:
        if not self.verdicts:
            return 0.0
        return sum(v.score for v in self.verdicts) / len(self.verdicts)


class EvalRunSummary(BaseModel):
    """Aggregate results from an evaluation run."""

    model_config = {"protected_namespaces": ()}

    run_id: str = Field(default_factory=lambda: f"eval_{uuid4().hex[:12]}")
    task_type: EvalTaskType
    model_used: str = ""
    prompt_version: str = ""
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    error_cases: int = 0
    pass_rate: float = 0.0

    # Per-metric aggregates
    metrics: dict[str, float] = Field(
        default_factory=dict,
        description="metric_name → average score across all cases.",
    )
    per_tag_metrics: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="tag → {metric_name → avg score} for per-tag breakdown.",
    )

    total_latency_ms: int = 0
    avg_latency_ms: float = 0.0
    total_cost_usd: float | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    results: list[EvalResult] = Field(default_factory=list)

    def compute_aggregates(self) -> None:
        """Recompute aggregate metrics from individual results."""
        self.total_cases = len(self.results)
        self.passed_cases = sum(1 for r in self.results if r.passed)
        self.failed_cases = sum(1 for r in self.results if not r.passed and not r.error)
        self.error_cases = sum(1 for r in self.results if r.error)
        self.pass_rate = self.passed_cases / self.total_cases if self.total_cases else 0.0
        self.total_latency_ms = sum(r.latency_ms for r in self.results)
        self.avg_latency_ms = (
            self.total_latency_ms / self.total_cases if self.total_cases else 0.0
        )

        # Per-metric averages
        metric_scores: dict[str, list[float]] = {}
        for r in self.results:
            for v in r.verdicts:
                metric_scores.setdefault(v.metric_name, []).append(v.score)
        self.metrics = {
            name: round(sum(scores) / len(scores), 4)
            for name, scores in metric_scores.items()
        }

    def summary_line(self) -> str:
        """One-line summary for CLI output."""
        return (
            f"[{self.task_type.value}] {self.passed_cases}/{self.total_cases} passed "
            f"({self.pass_rate:.0%}) | model={self.model_used} | "
            f"avg_latency={self.avg_latency_ms:.0f}ms"
        )
