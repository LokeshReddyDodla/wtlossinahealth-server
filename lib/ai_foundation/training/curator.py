"""
Quality Filter (Curator) — decides which captured LLM interactions are
good enough to use as training data.

Applies a multi-stage filter pipeline: structural validity, feedback
signals, automated eval scores, domain diversity, and PHI scrubbing.
Only samples passing all gates enter the training dataset.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore

logger = logging.getLogger(__name__)

SAMPLES_COLLECTION = "ai_finetune_samples"

# Regex patterns for PHI detection
_PHI_PATTERNS = [
    (re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"), "[PHONE]"),           # phone numbers
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),                      # SSN
    (re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"), "[DOB]"),                # dates that might be DOB
]


class SampleQualityScore(BaseModel):
    """Quality assessment for a single training sample."""

    sample_id: str
    structural_valid: bool = Field(description="Response parses into valid schema.")
    feedback_positive: bool | None = Field(
        default=None,
        description="True=thumbs up, False=thumbs down, None=no feedback.",
    )
    no_negative_signals: bool = Field(
        default=True,
        description="No implicit negative signals detected.",
    )
    eval_intent_accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    eval_safety: float = Field(default=1.0, ge=0.0, le=1.0)
    eval_grounding: float = Field(default=0.0, ge=0.0, le=1.0)
    domain_needed: bool = Field(
        default=False,
        description="True if this domain is underrepresented in training data.",
    )

    @property
    def composite_score(self) -> float:
        """Weighted aggregate quality score."""
        if not self.structural_valid or self.eval_safety < 1.0:
            return 0.0
        if self.feedback_positive is False:
            return 0.0

        base = (self.eval_intent_accuracy * 0.4 + self.eval_grounding * 0.3 + self.eval_safety * 0.3)
        if self.feedback_positive is True:
            base = min(1.0, base + 0.1)
        if self.domain_needed:
            base = min(1.0, base + 0.05)
        return round(base, 4)

    @property
    def eligible(self) -> bool:
        """Whether this sample passes all gates for training."""
        return (
            self.structural_valid
            and self.eval_safety == 1.0
            and self.feedback_positive is not False
            and self.no_negative_signals
            and self.composite_score >= 0.80
        )


class CurationStats(BaseModel):
    """Statistics from a curation run."""

    total_scanned: int = 0
    structural_invalid: int = 0
    negative_feedback: int = 0
    negative_signals: int = 0
    safety_failed: int = 0
    below_threshold: int = 0
    eligible: int = 0


class QualityFilter:
    """Filters captured LLM samples for training eligibility.

    Example::

        curator = QualityFilter(mongo_store)
        eligible, stats = await curator.filter_batch(
            task="intent_extraction",
            min_score=0.80,
            limit=5000,
        )
        print(f"{stats.eligible}/{stats.total_scanned} samples eligible")
    """

    def __init__(self, mongo_store: MongoStore | None = None) -> None:
        self._mongo = mongo_store

    async def score_sample(self, sample: dict[str, Any]) -> SampleQualityScore:
        """Score a single sample for training eligibility."""
        sample_id = sample.get("sample_id", "unknown")

        # 1. Structural validity
        structural = bool(sample.get("response")) and bool(sample.get("messages"))

        # 2. Feedback
        feedback_score = sample.get("feedback_score")
        feedback_positive: bool | None = None
        if feedback_score is not None:
            feedback_positive = feedback_score > 0.5

        # 3. Implicit signals
        signals = sample.get("implicit_signals", {})
        no_negative = not any([
            signals.get("user_asked_clarification_after"),
            signals.get("user_rephrased_same_question"),
            signals.get("care_provider_flagged"),
        ])

        # 4. Eval scores
        eval_scores = sample.get("eval_scores", {})
        intent_acc = eval_scores.get("intent_accuracy", eval_scores.get("data_types_recall", 0.0))
        safety = eval_scores.get("safety", 1.0)
        grounding = eval_scores.get("factual_grounding", eval_scores.get("grounding", 0.0))

        return SampleQualityScore(
            sample_id=sample_id,
            structural_valid=structural,
            feedback_positive=feedback_positive,
            no_negative_signals=no_negative,
            eval_intent_accuracy=intent_acc,
            eval_safety=safety,
            eval_grounding=grounding,
        )

    async def filter_batch(
        self,
        *,
        task: str | None = None,
        agent_id: str | None = None,
        min_score: float = 0.80,
        limit: int = 5000,
    ) -> tuple[list[dict[str, Any]], CurationStats]:
        """Filter a batch of samples from MongoDB.

        Returns:
            Tuple of (eligible_samples, stats).
        """
        if not self._mongo:
            return [], CurationStats()

        collection = self._mongo.get_collection(SAMPLES_COLLECTION)
        query: dict[str, Any] = {}
        if task:
            query["task"] = task
        if agent_id:
            query["agent_id"] = agent_id

        cursor = collection.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
        samples = await cursor.to_list(length=limit)

        stats = CurationStats(total_scanned=len(samples))
        eligible: list[dict[str, Any]] = []

        for sample in samples:
            score = await self.score_sample(sample)

            if not score.structural_valid:
                stats.structural_invalid += 1
                continue
            if score.feedback_positive is False:
                stats.negative_feedback += 1
                continue
            if not score.no_negative_signals:
                stats.negative_signals += 1
                continue
            if score.eval_safety < 1.0:
                stats.safety_failed += 1
                continue
            if score.composite_score < min_score:
                stats.below_threshold += 1
                continue

            # PHI scrub
            sample = self._scrub_phi(sample)
            sample["_quality_score"] = score.composite_score
            eligible.append(sample)
            stats.eligible += 1

        logger.info(
            "Curation complete: %d/%d eligible (task=%s)",
            stats.eligible,
            stats.total_scanned,
            task,
        )
        return eligible, stats

    @staticmethod
    def _scrub_phi(sample: dict[str, Any]) -> dict[str, Any]:
        """Remove potential PHI from sample text fields."""
        def scrub_text(text: str) -> str:
            for pattern, replacement in _PHI_PATTERNS:
                text = pattern.sub(replacement, text)
            return text

        # Scrub messages
        messages = sample.get("messages", [])
        for msg in messages:
            if isinstance(msg.get("content"), str):
                msg["content"] = scrub_text(msg["content"])

        # Scrub response
        if isinstance(sample.get("response"), str):
            sample["response"] = scrub_text(sample["response"])

        return sample
