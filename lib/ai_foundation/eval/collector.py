"""
Fine-Tune Data Collector — captures LLM I/O for future model training.

Every call through ModelGateway can optionally record a training sample
consisting of the input messages, output response, model used, and
quality signals (feedback, implicit signals, eval scores).

Samples are stored in MongoDB and later curated, filtered, and exported
for fine-tuning via the training pipeline.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore

logger = logging.getLogger(__name__)

SAMPLES_COLLECTION = "ai_finetune_samples"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ImplicitSignals(BaseModel):
    """Signals automatically inferred from user behaviour after a response."""

    user_asked_clarification_after: bool | None = Field(
        default=None,
        description="Next message was a clarification after is_ready=True → intent was wrong.",
    )
    user_rephrased_same_question: bool | None = Field(
        default=None,
        description="Next message covers same domain/date → response was unhelpful.",
    )
    conversation_continued: bool | None = Field(
        default=None,
        description="User sent another message → engaged (positive signal).",
    )
    care_provider_flagged: bool | None = Field(
        default=None,
        description="Care provider marked response as incorrect.",
    )


class TrainingSample(BaseModel):
    """A single captured LLM interaction for potential training use."""

    model_config = {"protected_namespaces": ()}

    sample_id: str = Field(default_factory=lambda: f"smp_{uuid4().hex[:16]}")
    agent_id: str
    task: str = Field(description="LLM task type, e.g. 'intent_extraction'.")
    model_id: str
    prompt_version: str | None = None

    # I/O
    messages: list[dict[str, Any]] = Field(description="Exact messages sent to LLM.")
    response: str = Field(description="Raw LLM output text.")
    structured_output: dict[str, Any] | None = Field(
        default=None,
        description="Parsed Pydantic model dump if extract() was used.",
    )

    # Quality signals
    feedback_score: float | None = Field(
        default=None,
        description="Explicit user feedback: 1.0=thumbs up, 0.0=thumbs down.",
    )
    implicit_signals: ImplicitSignals = Field(default_factory=ImplicitSignals)
    eval_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Automated eval harness scores, e.g. {'intent_accuracy': 0.92}.",
    )

    # Metadata
    patient_id_hash: str | None = Field(
        default=None, description="SHA-256 hash, never raw patient ID."
    )
    trace_id: str | None = None
    latency_ms: int | None = None
    cost_usd: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class FinetuneDataCollector:
    """Records LLM interactions as training samples in MongoDB.

    Designed to be injected into ``ModelGateway`` so that every call
    is captured automatically.

    Example::

        collector = FinetuneDataCollector(mongo_store)

        sample_id = await collector.record_sample(
            agent_id="health_query_v2",
            task="intent_extraction",
            model_id="gpt-4.1-mini",
            messages=[{"role": "system", "content": "..."}, ...],
            response='{"is_ready": true, ...}',
            structured_output={"is_ready": True, "data_types": ["cgm_range_stats"]},
            patient_id="p123",
            trace_id="trc_abc",
        )

        # Later, when user gives feedback
        await collector.add_feedback(sample_id, score=1.0, notes="accurate")
    """

    def __init__(
        self,
        mongo_store: MongoStore | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        self._mongo = mongo_store
        self._enabled = enabled

    async def record_sample(
        self,
        *,
        agent_id: str,
        task: str,
        model_id: str,
        messages: list[dict[str, Any]],
        response: str,
        structured_output: dict[str, Any] | None = None,
        patient_id: str | None = None,
        trace_id: str | None = None,
        prompt_version: str | None = None,
        latency_ms: int | None = None,
        cost_usd: float | None = None,
    ) -> str | None:
        """Record a training sample. Returns the sample_id or None if disabled."""
        if not self._enabled or not self._mongo:
            return None

        patient_hash = (
            hashlib.sha256(patient_id.encode()).hexdigest()[:16]
            if patient_id
            else None
        )

        sample = TrainingSample(
            agent_id=agent_id,
            task=task,
            model_id=model_id,
            messages=messages,
            response=response,
            structured_output=structured_output,
            patient_id_hash=patient_hash,
            trace_id=trace_id,
            prompt_version=prompt_version,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )

        try:
            collection = self._mongo.get_collection(SAMPLES_COLLECTION)
            await collection.insert_one(
                sample.model_dump(mode="json", exclude_none=True)
            )
            logger.debug("Recorded training sample %s", sample.sample_id)
            return sample.sample_id
        except Exception as exc:
            logger.warning("Failed to record training sample: %s", exc)
            return None

    async def add_feedback(
        self,
        sample_id: str,
        score: float,
        notes: str | None = None,
    ) -> bool:
        """Add explicit user feedback to a sample.

        Args:
            sample_id: The sample to update.
            score: 1.0 for thumbs-up, 0.0 for thumbs-down.
            notes: Optional free-text feedback.

        Returns:
            True if the update succeeded.
        """
        if not self._mongo:
            return False

        try:
            collection = self._mongo.get_collection(SAMPLES_COLLECTION)
            result = await collection.update_one(
                {"sample_id": sample_id},
                {
                    "$set": {
                        "feedback_score": score,
                        "feedback_notes": notes,
                        "feedback_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
            )
            return result.modified_count > 0
        except Exception as exc:
            logger.warning("Failed to add feedback to %s: %s", sample_id, exc)
            return False

    async def add_implicit_signal(
        self,
        sample_id: str,
        signal: str,
        value: bool,
    ) -> bool:
        """Add an implicit quality signal to a sample.

        Args:
            sample_id: The sample to update.
            signal: Signal name (must be a field of ``ImplicitSignals``).
            value: Signal value.
        """
        if not self._mongo:
            return False

        try:
            collection = self._mongo.get_collection(SAMPLES_COLLECTION)
            result = await collection.update_one(
                {"sample_id": sample_id},
                {"$set": {f"implicit_signals.{signal}": value}},
            )
            return result.modified_count > 0
        except Exception as exc:
            logger.warning("Failed to add implicit signal to %s: %s", sample_id, exc)
            return False

    async def add_eval_scores(
        self,
        sample_id: str,
        scores: dict[str, float],
    ) -> bool:
        """Add automated evaluation scores to a sample."""
        if not self._mongo:
            return False

        try:
            collection = self._mongo.get_collection(SAMPLES_COLLECTION)
            result = await collection.update_one(
                {"sample_id": sample_id},
                {"$set": {f"eval_scores.{k}": v for k, v in scores.items()}},
            )
            return result.modified_count > 0
        except Exception as exc:
            logger.warning("Failed to add eval scores to %s: %s", sample_id, exc)
            return False

    async def get_sample(self, sample_id: str) -> dict | None:
        """Retrieve a single sample."""
        if not self._mongo:
            return None
        collection = self._mongo.get_collection(SAMPLES_COLLECTION)
        return await collection.find_one({"sample_id": sample_id}, {"_id": 0})

    async def count_samples(
        self,
        *,
        agent_id: str | None = None,
        task: str | None = None,
        has_feedback: bool | None = None,
    ) -> int:
        """Count samples matching criteria."""
        if not self._mongo:
            return 0

        query: dict[str, Any] = {}
        if agent_id:
            query["agent_id"] = agent_id
        if task:
            query["task"] = task
        if has_feedback is True:
            query["feedback_score"] = {"$ne": None}
        elif has_feedback is False:
            query["feedback_score"] = None

        collection = self._mongo.get_collection(SAMPLES_COLLECTION)
        return await collection.count_documents(query)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
