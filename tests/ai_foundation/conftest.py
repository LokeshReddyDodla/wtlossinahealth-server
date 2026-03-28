"""Shared fixtures for AI Foundation tests."""

from __future__ import annotations

import pytest

from lib.ai_foundation.models.registry import (
    ModelRegistry,
    ModelSpec,
    ModelTask,
    ModelProvider,
    build_default_registry,
)
from lib.ai_foundation.models.circuit_breaker import CircuitBreaker
from lib.ai_foundation.prompts.registry import PromptRegistry
from lib.ai_foundation.events.bus import EventBus


@pytest.fixture
def registry() -> ModelRegistry:
    return build_default_registry()


@pytest.fixture
def circuit_breaker() -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=3, window_seconds=60, cooldown_seconds=1)


@pytest.fixture
def prompt_registry() -> PromptRegistry:
    return PromptRegistry()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()
