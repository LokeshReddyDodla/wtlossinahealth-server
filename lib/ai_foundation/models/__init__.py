"""LLM Gateway & Routing — unified interface for all model calls."""

from .registry import (
    ModelGatewayError,
    ModelNotFoundError,
    ModelProvider,
    ModelRegistry,
    ModelSpec,
    ModelTask,
    NoRouteError,
    TaskRoute,
    build_default_registry,
)
from .circuit_breaker import CircuitBreaker, CircuitState, CircuitStats
from .pricing import CostBreakdown, PricingCalculator, TokenUsage

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "CircuitStats",
    "CostBreakdown",
    "ModelGatewayError",
    "ModelNotFoundError",
    "ModelProvider",
    "ModelRegistry",
    "ModelSpec",
    "ModelTask",
    "NoRouteError",
    "PricingCalculator",
    "TaskRoute",
    "TokenUsage",
    "build_default_registry",
]


def __getattr__(name: str):
    """Lazy imports for modules that depend on external packages (openai, instructor)."""
    if name in ("LLMResponse", "LLMUsage", "ModelGateway", "StreamChunk", "AllProvidersUnavailableError",
                 "ToolCall", "LLMToolResponse"):
        from .gateway import LLMResponse, LLMUsage, ModelGateway, StreamChunk, AllProvidersUnavailableError, ToolCall, LLMToolResponse
        return {
            "LLMResponse": LLMResponse,
            "LLMUsage": LLMUsage,
            "ModelGateway": ModelGateway,
            "StreamChunk": StreamChunk,
            "AllProvidersUnavailableError": AllProvidersUnavailableError,
            "ToolCall": ToolCall,
            "LLMToolResponse": LLMToolResponse,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
