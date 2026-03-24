"""
Model Registry — central configuration for all LLM models and task-based routing.

The registry maps tasks (intent extraction, response generation, etc.) to model
specifications, supporting fallback chains so that provider outages are handled
transparently.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ModelGatewayError(Exception):
    """Base exception for all model gateway errors."""


class ModelNotFoundError(ModelGatewayError):
    """Raised when a requested model is not registered."""


class NoRouteError(ModelGatewayError):
    """Raised when no route is configured for a given task."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ModelTask(str, Enum):
    """Identifies the purpose of an LLM call — drives model selection."""

    INTENT_EXTRACTION = "intent_extraction"
    RESPONSE_GENERATION = "response_generation"
    STRUCTURED_ANALYSIS = "structured_analysis"
    CLASSIFICATION = "classification"
    SUMMARIZATION = "summarization"
    EMBEDDING = "embedding"
    QUALITY_JUDGE = "quality_judge"


class ModelProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    LOCAL = "local"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ModelSpec(BaseModel):
    """Configuration for a single LLM model."""

    model_config = {"protected_namespaces": ()}

    model_id: str = Field(
        ..., description="Provider model identifier, e.g. 'gpt-4.1-mini'."
    )
    provider: ModelProvider = Field(
        default=ModelProvider.OPENAI,
        description="Which LLM provider hosts this model.",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Sampling temperature.",
    )
    max_tokens: int | None = Field(
        default=None,
        description="Maximum tokens in the response. None = provider default.",
    )
    timeout_seconds: float = Field(
        default=12.0,
        gt=0,
        description="Per-call timeout in seconds.",
    )
    cost_per_1k_input: float = Field(
        default=0.0,
        ge=0,
        description="Cost in USD per 1 000 input tokens.",
    )
    cost_per_1k_output: float = Field(
        default=0.0,
        ge=0,
        description="Cost in USD per 1 000 output tokens.",
    )
    supports_structured: bool = Field(
        default=True,
        description="Whether the model supports structured (JSON) output via Instructor.",
    )
    supports_streaming: bool = Field(
        default=True,
        description="Whether the model supports token streaming.",
    )
    supports_vision: bool = Field(
        default=False,
        description="Whether the model accepts image inputs.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Arbitrary tags for filtering, e.g. ['fast', 'cheap', 'reasoning'].",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific configuration overrides.",
    )

    def with_overrides(self, **kwargs: Any) -> ModelSpec:
        """Return a copy with the given fields overridden."""
        data = self.model_dump()
        data.update(kwargs)
        return ModelSpec(**data)


class TaskRoute(BaseModel):
    """Maps a task to a primary model and an ordered list of fallbacks."""

    primary: str = Field(
        ..., description="Model ID of the primary model for this task."
    )
    fallbacks: list[str] = Field(
        default_factory=list,
        description="Ordered fallback model IDs tried when the primary fails.",
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ModelRegistry:
    """Central registry mapping tasks to model specs with fallback chains.

    Thread-safe for reads after initial configuration. Not designed for
    concurrent writes — configure at startup, then treat as read-only.

    Example::

        registry = ModelRegistry()
        registry.register(ModelSpec(model_id="gpt-4.1-mini", provider="openai", ...))
        registry.register(ModelSpec(model_id="gpt-5.1", provider="openai", ...))

        registry.set_task_route(
            ModelTask.INTENT_EXTRACTION,
            primary="gpt-4.1-mini",
            fallbacks=["gpt-5.1"],
        )

        spec = registry.route(ModelTask.INTENT_EXTRACTION)  # → gpt-4.1-mini spec
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelSpec] = {}
        self._routes: dict[ModelTask, TaskRoute] = {}

    # -- Registration -------------------------------------------------------

    def register(self, spec: ModelSpec) -> None:
        """Register a model specification. Overwrites if model_id already exists."""
        self._models[spec.model_id] = deepcopy(spec)
        logger.debug("Registered model %s (provider=%s)", spec.model_id, spec.provider)

    def register_many(self, specs: list[ModelSpec]) -> None:
        """Convenience: register multiple models at once."""
        for spec in specs:
            self.register(spec)

    # -- Routing ------------------------------------------------------------

    def set_task_route(
        self,
        task: ModelTask,
        primary: str,
        fallbacks: list[str] | None = None,
    ) -> None:
        """Configure which model(s) handle a given task.

        Args:
            task: The task type to route.
            primary: Model ID of the primary model.
            fallbacks: Ordered list of fallback model IDs.

        Raises:
            ModelNotFoundError: If any referenced model ID is not registered.
        """
        all_ids = [primary, *(fallbacks or [])]
        for model_id in all_ids:
            if model_id not in self._models:
                raise ModelNotFoundError(
                    f"Cannot route task {task.value!r} to unregistered model {model_id!r}. "
                    f"Call registry.register() first."
                )
        self._routes[task] = TaskRoute(primary=primary, fallbacks=fallbacks or [])
        logger.debug(
            "Task route: %s → primary=%s fallbacks=%s",
            task.value,
            primary,
            fallbacks or [],
        )

    def route(self, task: ModelTask) -> ModelSpec:
        """Resolve the primary model spec for a task.

        Raises:
            NoRouteError: If no route is configured for the task.
        """
        task_route = self._routes.get(task)
        if task_route is None:
            raise NoRouteError(
                f"No route configured for task {task.value!r}. "
                f"Call registry.set_task_route() first."
            )
        return self.get(task_route.primary)

    def get_task_route(self, task: ModelTask) -> TaskRoute:
        """Return the full TaskRoute (primary + fallbacks) for a task.

        Raises:
            NoRouteError: If no route is configured for the task.
        """
        task_route = self._routes.get(task)
        if task_route is None:
            raise NoRouteError(
                f"No route configured for task {task.value!r}."
            )
        return deepcopy(task_route)

    def get_fallback_chain(self, task: ModelTask) -> list[ModelSpec]:
        """Return ordered list of all model specs for a task (primary first, then fallbacks).

        Raises:
            NoRouteError: If no route is configured for the task.
        """
        task_route = self.get_task_route(task)
        return [self.get(mid) for mid in [task_route.primary, *task_route.fallbacks]]

    # -- Lookup -------------------------------------------------------------

    def get(self, model_id: str) -> ModelSpec:
        """Return a copy of the spec for a registered model.

        Raises:
            ModelNotFoundError: If the model ID is not registered.
        """
        spec = self._models.get(model_id)
        if spec is None:
            raise ModelNotFoundError(
                f"Model {model_id!r} is not registered. "
                f"Available: {sorted(self._models.keys())}"
            )
        return deepcopy(spec)

    def list_models(self, *, tags: list[str] | None = None) -> list[ModelSpec]:
        """List all registered models, optionally filtered by tags."""
        specs = list(self._models.values())
        if tags:
            tag_set = set(tags)
            specs = [s for s in specs if tag_set.issubset(set(s.tags))]
        return [deepcopy(s) for s in specs]

    def list_tasks(self) -> dict[ModelTask, TaskRoute]:
        """Return a snapshot of all configured task routes."""
        return {task: deepcopy(route) for task, route in self._routes.items()}

    # -- Utilities ----------------------------------------------------------

    def __contains__(self, model_id: str) -> bool:
        return model_id in self._models

    def __repr__(self) -> str:
        models = sorted(self._models.keys())
        routes = {t.value: r.primary for t, r in self._routes.items()}
        return f"ModelRegistry(models={models}, routes={routes})"


# ---------------------------------------------------------------------------
# Default registry factory
# ---------------------------------------------------------------------------


def build_default_registry() -> ModelRegistry:
    """Build a registry pre-loaded with common OpenAI models and sensible routes.

    This is a convenience for bootstrapping. Production deployments should
    configure the registry explicitly via environment or config.
    """
    registry = ModelRegistry()

    registry.register_many([
        ModelSpec(
            model_id="gpt-4.1-mini",
            provider=ModelProvider.OPENAI,
            temperature=0.0,
            timeout_seconds=10.0,
            cost_per_1k_input=0.0004,
            cost_per_1k_output=0.0016,
            supports_structured=True,
            supports_streaming=True,
            tags=["fast", "cheap", "structured"],
        ),
        ModelSpec(
            model_id="gpt-4.1",
            provider=ModelProvider.OPENAI,
            temperature=0.0,
            timeout_seconds=15.0,
            cost_per_1k_input=0.002,
            cost_per_1k_output=0.008,
            supports_structured=True,
            supports_streaming=True,
            tags=["balanced", "structured"],
        ),
        ModelSpec(
            model_id="gpt-5.1",
            provider=ModelProvider.OPENAI,
            temperature=0.0,
            timeout_seconds=20.0,
            cost_per_1k_input=0.005,
            cost_per_1k_output=0.015,
            supports_structured=True,
            supports_streaming=True,
            tags=["powerful", "reasoning"],
        ),
        ModelSpec(
            model_id="text-embedding-3-large",
            provider=ModelProvider.OPENAI,
            timeout_seconds=5.0,
            cost_per_1k_input=0.00013,
            cost_per_1k_output=0.0,
            supports_structured=False,
            supports_streaming=False,
            tags=["embedding"],
        ),
    ])

    registry.set_task_route(
        ModelTask.INTENT_EXTRACTION,
        primary="gpt-4.1-mini",
        fallbacks=["gpt-4.1"],
    )
    registry.set_task_route(
        ModelTask.RESPONSE_GENERATION,
        primary="gpt-5.1",
        fallbacks=["gpt-4.1", "gpt-4.1-mini"],
    )
    registry.set_task_route(
        ModelTask.STRUCTURED_ANALYSIS,
        primary="gpt-4.1-mini",
        fallbacks=["gpt-4.1"],
    )
    registry.set_task_route(
        ModelTask.CLASSIFICATION,
        primary="gpt-4.1-mini",
    )
    registry.set_task_route(
        ModelTask.SUMMARIZATION,
        primary="gpt-4.1-mini",
        fallbacks=["gpt-4.1"],
    )
    registry.set_task_route(
        ModelTask.EMBEDDING,
        primary="text-embedding-3-large",
    )
    registry.set_task_route(
        ModelTask.QUALITY_JUDGE,
        primary="gpt-4.1",
        fallbacks=["gpt-4.1-mini"],
    )

    return registry
