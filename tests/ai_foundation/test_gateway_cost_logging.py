"""Gateway emits USD cost to Langfuse via cost_details (not usage.total_cost).

langfuse SDK 2.60.10 silently drops a `usage` dict's snake_case `total_cost`;
only `cost_details={"total": ...}` is ingested. This locks the shape.
"""

import types

from lib.ai_foundation.models.gateway import LLMUsage, ModelGateway
from lib.ai_foundation.models.pricing import CostBreakdown


class _StubLangfuse:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generation(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_log_generation_uses_cost_details() -> None:
    stub = _StubLangfuse()
    fake = types.SimpleNamespace(_langfuse_client=stub)

    ModelGateway._log_generation(
        fake,
        trace_id="t1",
        model="gpt-5.1",
        input_messages=[{"role": "user", "content": "hi"}],
        output_text="ok",
        prompt_tokens=100,
        completion_tokens=20,
        cost_usd=0.0123,
    )

    assert len(stub.calls) == 1
    kw = stub.calls[0]
    assert kw["cost_details"] == {"total": 0.0123}, "USD must go through cost_details"
    assert kw["usage_details"] == {"input": 100, "output": 20}
    assert kw["trace_id"] == "t1"
    assert kw["model"] == "gpt-5.1"
    assert "usage" not in kw, "the deprecated usage dict silently drops snake_case cost"


def test_log_generation_no_client_is_noop() -> None:
    fake = types.SimpleNamespace(_langfuse_client=None)
    # Must not raise when Langfuse is disabled.
    ModelGateway._log_generation(
        fake, trace_id="t", model="m", input_messages=None,
        output_text="", prompt_tokens=0, completion_tokens=0, cost_usd=0.0,
    )


def test_resolve_cost_prefers_litellm_response_cost() -> None:
    usage = LLMUsage(cost=CostBreakdown(total_cost=0.05))
    assert ModelGateway._resolve_cost(raw=None, usage=usage, model="gpt-5.1") == 0.05


def test_resolve_cost_falls_back_to_zero_when_unpriced() -> None:
    # response_cost 0 + no priceable raw response -> 0.0, never crashes logging.
    usage = LLMUsage(cost=CostBreakdown(total_cost=0.0))
    assert ModelGateway._resolve_cost(raw=None, usage=usage, model="gpt-5.1") == 0.0


if __name__ == "__main__":
    test_log_generation_uses_cost_details()
    test_log_generation_no_client_is_noop()
    test_resolve_cost_prefers_litellm_response_cost()
    test_resolve_cost_falls_back_to_zero_when_unpriced()
    print("ok")
