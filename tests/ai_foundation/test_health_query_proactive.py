"""The one brain, triggered by an event instead of a question.

`run_proactive` reuses the reasoning engine + real prompts, skips triage, and
returns a push-shaped decision. The brain may decline to notify; category and
severity are NOT its job (the caller derives those from the trigger).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lib.ai_foundation.agents.health_query.agent import HealthQueryAgent
from lib.ai_foundation.agents.health_query.contracts import ProactiveNarration
from lib.ai_foundation.agents.health_query.reasoning_engine import ReasoningResult, ReasoningTier
from lib.ai_foundation.prompts.registry import PromptRegistry

_PROMPTS = Path("lib/ai_foundation/agents/health_query/prompts")


def _agent(*, narration: ProactiveNarration, engine_response: str = "analysis prose"):
    prompts = PromptRegistry()
    prompts.register_directory(_PROMPTS, namespace="health_query")

    engine = AsyncMock()
    engine.reason = AsyncMock(return_value=ReasoningResult(response=engine_response, tier="standard"))

    gateway = AsyncMock()
    gateway.extract = AsyncMock(return_value=(narration, AsyncMock()))

    context_loader = AsyncMock()
    context_loader.load = AsyncMock(return_value=object())  # engine is mocked; ctx unused

    return HealthQueryAgent(
        gateway=gateway, prompts=prompts,
        reasoning_engine=engine, context_loader=context_loader,
    ), engine, gateway


@pytest.mark.asyncio
async def test_run_proactive_returns_structured_push():
    want = ProactiveNarration(notify=True, title="Glucose running high",
                              body="You reached 190 after lunch — higher than your usual.",
                              suggested_query="What drove this?")
    agent, engine, gateway = _agent(narration=want)

    got = await agent.run_proactive(
        patient_id="p1", event_summary="Glucose crossed into hyper at 190.",
        tier=ReasoningTier.ADVANCED,
    )

    assert got.notify is True and got.title == want.title and got.body == want.body
    # the chosen tier is honored, and the event is the prompt (no triage)
    assert engine.reason.call_args.kwargs["tier"] is ReasoningTier.ADVANCED
    assert engine.reason.call_args.kwargs["user_message"] == "Glucose crossed into hyper at 190."
    # structuring reads the brain's own analysis, nothing else
    assert gateway.extract.call_args.kwargs["messages"][-1]["content"] == "analysis prose"


@pytest.mark.asyncio
async def test_run_proactive_can_decline_to_notify():
    agent, _, _ = _agent(narration=ProactiveNarration(notify=False))
    got = await agent.run_proactive(patient_id="p1", event_summary="A meal was logged.")
    assert got.notify is False


def test_narration_body_and_title_are_length_bounded():
    # the push contract the model must fit — pydantic enforces the ceilings
    with pytest.raises(ValueError):
        ProactiveNarration(notify=True, title="x" * 51, body="ok")
    with pytest.raises(ValueError):
        ProactiveNarration(notify=True, title="ok", body="y" * 181)
