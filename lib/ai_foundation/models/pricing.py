"""
Pricing Calculator — computes USD cost from token usage and model specs.

Centralizes cost tracking so every LLM call made through the ModelGateway
automatically reports its cost. Supports cached-token discounts.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .registry import ModelSpec


class TokenUsage(BaseModel):
    """Raw token counts from an LLM response."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(
        default=0,
        ge=0,
        description="Input tokens served from provider cache (e.g. OpenAI prompt caching).",
    )


class CostBreakdown(BaseModel):
    """Itemised cost for a single LLM call."""

    input_cost: float = Field(default=0.0, ge=0)
    output_cost: float = Field(default=0.0, ge=0)
    cached_discount: float = Field(
        default=0.0,
        ge=0,
        description="Savings from cached input tokens.",
    )
    total_cost: float = Field(default=0.0, ge=0)


class PricingCalculator:
    """Stateless calculator that turns token counts into USD costs.

    Provider prompt-caching typically charges 50 % of the normal input rate
    for cached tokens. The ``cached_discount_rate`` controls this.
    """

    CACHED_DISCOUNT_RATE: float = 0.5  # cached tokens cost 50% of normal

    @classmethod
    def calculate(cls, spec: ModelSpec, usage: TokenUsage) -> CostBreakdown:
        """Compute cost breakdown for a single call.

        Args:
            spec: The model specification (contains per-1k-token prices).
            usage: Token counts from the provider response.

        Returns:
            Itemised ``CostBreakdown``.
        """
        billable_input = max(0, usage.input_tokens - usage.cached_tokens)
        input_cost = (billable_input / 1_000) * spec.cost_per_1k_input
        cached_cost = (
            (usage.cached_tokens / 1_000)
            * spec.cost_per_1k_input
            * cls.CACHED_DISCOUNT_RATE
        )
        output_cost = (usage.output_tokens / 1_000) * spec.cost_per_1k_output

        full_input_cost = (usage.input_tokens / 1_000) * spec.cost_per_1k_input
        cached_discount = full_input_cost - (input_cost + cached_cost)

        total = input_cost + cached_cost + output_cost

        return CostBreakdown(
            input_cost=round(input_cost + cached_cost, 8),
            output_cost=round(output_cost, 8),
            cached_discount=round(max(cached_discount, 0.0), 8),
            total_cost=round(total, 8),
        )
