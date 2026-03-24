"""
A/B Test Manager — safe canary deployment of fine-tuned models.

Manages traffic splitting between control (current production) and
treatment (new fine-tuned) models. Supports gradual ramp-up and
automatic rollback if metrics degrade.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from lib.ai_foundation.models.registry import ModelTask

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore

logger = logging.getLogger(__name__)

AB_TESTS_COLLECTION = "ai_ab_tests"


class ABTestConfig(BaseModel):
    """Configuration for an A/B test between two models."""

    model_config = {"protected_namespaces": ()}

    test_id: str = Field(description="Unique test identifier.")
    task: ModelTask = Field(description="Which task is being tested.")
    control_model: str = Field(description="Current production model ID.")
    treatment_model: str = Field(description="New model ID to test.")
    traffic_split: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Fraction of traffic routed to treatment (0.0-1.0).",
    )
    auto_rollback_threshold: float = Field(
        default=0.05,
        description="Rollback if any metric degrades by more than this fraction.",
    )
    min_sample_size: int = Field(
        default=200,
        description="Minimum requests before results are considered significant.",
    )
    status: str = Field(
        default="active",
        description="'active', 'paused', 'completed', 'rolled_back'.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ABTestMetrics(BaseModel):
    """Collected metrics for one variant of an A/B test."""

    model_config = {"protected_namespaces": ()}

    model_id: str
    request_count: int = 0
    avg_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    error_rate: float = 0.0
    avg_quality_score: float = 0.0
    positive_feedback_rate: float = 0.0


class ABTestResults(BaseModel):
    """Comparison results for an A/B test."""

    model_config = {"protected_namespaces": ()}

    test_id: str
    control: ABTestMetrics
    treatment: ABTestMetrics
    significant: bool = Field(
        default=False,
        description="Whether we have enough samples for significance.",
    )
    treatment_better: bool = False
    should_rollback: bool = False
    recommendation: str = ""


class ABTestManager:
    """Manages A/B tests for model comparison.

    Integrates with ModelGateway to route traffic and with TraceCollector
    to collect per-variant metrics.

    Example::

        manager = ABTestManager(mongo_store)

        # Create a test
        await manager.create_test(ABTestConfig(
            test_id="intent-v3-test",
            task=ModelTask.INTENT_EXTRACTION,
            control_model="gpt-4.1-mini",
            treatment_model="ft:gpt-4.1-mini:org:health-intent-v3",
            traffic_split=0.05,
        ))

        # Route a request (called by ModelGateway)
        model_id = await manager.get_routing_decision(ModelTask.INTENT_EXTRACTION)

        # After collecting enough data
        results = await manager.analyze_results("intent-v3-test")
        if results.treatment_better:
            await manager.promote_treatment("intent-v3-test")
    """

    def __init__(self, mongo_store: MongoStore | None = None) -> None:
        self._mongo = mongo_store
        self._active_tests: dict[str, ABTestConfig] = {}

    async def create_test(self, config: ABTestConfig) -> None:
        """Create and activate an A/B test."""
        self._active_tests[config.test_id] = config

        if self._mongo:
            collection = self._mongo.get_collection(AB_TESTS_COLLECTION)
            await collection.replace_one(
                {"test_id": config.test_id},
                config.model_dump(mode="json"),
                upsert=True,
            )

        logger.info(
            "A/B test created: %s (%s vs %s, split=%.0f%%)",
            config.test_id,
            config.control_model,
            config.treatment_model,
            config.traffic_split * 100,
        )

    async def get_routing_decision(self, task: ModelTask) -> str | None:
        """Determine which model to use for a given task.

        Returns the model_id to use, or None if no active test
        exists for this task (use default routing).
        """
        for config in self._active_tests.values():
            if config.task == task and config.status == "active":
                if random.random() < config.traffic_split:
                    return config.treatment_model
                return config.control_model
        return None

    async def update_split(self, test_id: str, new_split: float) -> None:
        """Update the traffic split for a test (ramp up/down)."""
        config = self._active_tests.get(test_id)
        if not config:
            raise ValueError(f"Test {test_id!r} not found.")

        config.traffic_split = max(0.0, min(1.0, new_split))
        config.updated_at = datetime.now(timezone.utc)

        if self._mongo:
            collection = self._mongo.get_collection(AB_TESTS_COLLECTION)
            await collection.update_one(
                {"test_id": test_id},
                {"$set": {
                    "traffic_split": config.traffic_split,
                    "updated_at": config.updated_at.isoformat(),
                }},
            )

        logger.info("A/B test %s: split updated to %.0f%%", test_id, config.traffic_split * 100)

    async def promote_treatment(self, test_id: str) -> str:
        """Promote the treatment model to production (100% traffic).

        Returns the treatment model_id for the caller to update ModelRegistry.
        """
        config = self._active_tests.get(test_id)
        if not config:
            raise ValueError(f"Test {test_id!r} not found.")

        config.status = "completed"
        config.traffic_split = 1.0
        config.updated_at = datetime.now(timezone.utc)

        if self._mongo:
            collection = self._mongo.get_collection(AB_TESTS_COLLECTION)
            await collection.update_one(
                {"test_id": test_id},
                {"$set": {
                    "status": "completed",
                    "traffic_split": 1.0,
                    "updated_at": config.updated_at.isoformat(),
                }},
            )

        logger.info(
            "A/B test %s: treatment %s promoted to production!",
            test_id,
            config.treatment_model,
        )
        return config.treatment_model

    async def rollback(self, test_id: str) -> None:
        """Rollback: route 100% traffic back to control model."""
        config = self._active_tests.get(test_id)
        if not config:
            raise ValueError(f"Test {test_id!r} not found.")

        config.status = "rolled_back"
        config.traffic_split = 0.0
        config.updated_at = datetime.now(timezone.utc)

        if self._mongo:
            collection = self._mongo.get_collection(AB_TESTS_COLLECTION)
            await collection.update_one(
                {"test_id": test_id},
                {"$set": {
                    "status": "rolled_back",
                    "traffic_split": 0.0,
                    "updated_at": config.updated_at.isoformat(),
                }},
            )

        logger.warning("A/B test %s: ROLLED BACK to %s", test_id, config.control_model)

    async def get_test(self, test_id: str) -> ABTestConfig | None:
        """Retrieve an A/B test configuration."""
        return self._active_tests.get(test_id)

    async def list_active_tests(self) -> list[ABTestConfig]:
        """List all active A/B tests."""
        return [c for c in self._active_tests.values() if c.status == "active"]
