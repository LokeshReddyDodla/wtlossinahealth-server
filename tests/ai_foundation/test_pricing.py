"""Tests for PricingCalculator — cost computation from token usage."""

from lib.ai_foundation.models.pricing import CostBreakdown, PricingCalculator, TokenUsage
from lib.ai_foundation.models.registry import ModelSpec


class TestPricingCalculator:
    def _spec(self, cost_in: float = 0.002, cost_out: float = 0.008) -> ModelSpec:
        return ModelSpec(
            model_id="test",
            cost_per_1k_input=cost_in,
            cost_per_1k_output=cost_out,
        )

    def test_basic_cost(self):
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost = PricingCalculator.calculate(self._spec(), usage)
        assert cost.input_cost == pytest.approx(0.002, abs=1e-6)
        assert cost.output_cost == pytest.approx(0.004, abs=1e-6)
        assert cost.total_cost == pytest.approx(0.006, abs=1e-6)

    def test_zero_tokens(self):
        usage = TokenUsage(input_tokens=0, output_tokens=0)
        cost = PricingCalculator.calculate(self._spec(), usage)
        assert cost.total_cost == 0.0

    def test_cached_tokens_discount(self):
        usage = TokenUsage(input_tokens=1000, output_tokens=500, cached_tokens=400)
        cost = PricingCalculator.calculate(self._spec(), usage)
        # 600 billable input at full rate + 400 cached at 50% rate
        expected_input = (600 / 1000 * 0.002) + (400 / 1000 * 0.002 * 0.5)
        assert cost.input_cost == pytest.approx(expected_input, abs=1e-6)
        assert cost.cached_discount > 0

    def test_all_cached(self):
        usage = TokenUsage(input_tokens=1000, output_tokens=0, cached_tokens=1000)
        cost = PricingCalculator.calculate(self._spec(), usage)
        # All input cached at 50%
        expected = 1000 / 1000 * 0.002 * 0.5
        assert cost.input_cost == pytest.approx(expected, abs=1e-6)
        assert cost.output_cost == 0.0

    def test_free_model(self):
        spec = ModelSpec(model_id="free", cost_per_1k_input=0.0, cost_per_1k_output=0.0)
        usage = TokenUsage(input_tokens=5000, output_tokens=2000)
        cost = PricingCalculator.calculate(spec, usage)
        assert cost.total_cost == 0.0


import pytest
