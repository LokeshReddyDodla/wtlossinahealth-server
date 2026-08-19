"""Gateway emits USD cost via the OpenAI-style usage dict.

The self-hosted Langfuse 2.95 server ingests cost only from a `usage` dict
with prompt_tokens/completion_tokens/total_cost (converted to totalCost by
_convert_usage_input); usage_details/cost_details log 0. This locks the shape.
"""

import types

from lib.ai_foundation.models.gateway import LLMUsage, ModelGateway
from lib.ai_foundation.models.pricing import CostBreakdown


class _StubLangfuse:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generation(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_log_generation_uses_openai_usage_dict() -> None:
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
    assert kw["usage"] == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_cost": 0.0123,
    }, "cost/tokens must go through the OpenAI-style usage dict"
    assert kw["trace_id"] == "t1"
    assert kw["model"] == "gpt-5.1"
    assert "cost_details" not in kw, "cost_details is not ingested by the 2.95 server"


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
    test_log_generation_uses_openai_usage_dict()
    test_log_generation_no_client_is_noop()
    test_resolve_cost_prefers_litellm_response_cost()
    test_resolve_cost_falls_back_to_zero_when_unpriced()
    print("ok")
