"""Execute the REAL streaming responder paths (engine + coordinator).

The done-payload/token protocol is otherwise only exercised with
reason_stream/orchestrate_stream mocked away — a scope or protocol bug in
the real generator (e.g. an undefined name that only trips at the first
delta) ships invisibly. These tests run the genuine _reason_core /
_orchestrate_core code with only the gateway/tool boundary stubbed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.agents.core.context_loader import AgentContext
from lib.ai_foundation.agents.health_query.reasoning_engine import (
    ReasoningEngine,
    ReasoningTier,
)
from lib.ai_foundation.streaming.sse import SSEDonePayload


class _Chunk:
    def __init__(self, delta: str = "", finished: bool = False):
        self.delta = delta
        self.finished = finished
        self.usage = None
        self.model_id = "test-model"
        self.cost_usd = 0.0


def _streaming_gateway(deltas: list[str]):
    """Gateway stub: thinker answers with no tool calls, responder streams."""
    gw = MagicMock()

    thinker_resp = MagicMock()
    thinker_resp.tool_calls = []
    thinker_resp.has_tool_calls = False
    thinker_resp.content = "DONE gathering."
    thinker_resp.cost_usd = 0.0
    thinker_resp.model_id = "thinker"
    gw.complete_with_tools = AsyncMock(return_value=thinker_resp)

    reflection = MagicMock()
    reflection.content = '{"is_complete": true, "confidence": 0.9, "gaps": [], "conflicts": []}'
    reflection.cost_usd = 0.0
    gw.complete = AsyncMock(return_value=reflection)
    gw.extract = AsyncMock(side_effect=Exception("no structured calls expected"))
    gw.count_tokens = MagicMock(return_value=100)
    gw.get_model_window = MagicMock(return_value=128_000)

    async def _stream(**kwargs):
        for d in deltas:
            yield _Chunk(delta=d)
        yield _Chunk(finished=True)

    gw.stream = _stream
    return gw


def _tools():
    tools = MagicMock()
    tools.get_openai_schemas = MagicMock(return_value=[])
    tools.execute = AsyncMock(return_value="NO_DATA: nothing")
    tools.execute_tool_round = AsyncMock()
    return tools


def _ctx() -> AgentContext:
    return AgentContext(history=[], facts=[], patient_names={"p1": "Asha"})


@pytest.mark.asyncio
async def test_engine_stream_real_path_tokens_sink_and_done():
    gw = _streaming_gateway(["Hello ", "[[BUBBLE]]", "world [[AWAIT:meal]]"])
    engine = ReasoningEngine(gateway=gw, tool_executor=_tools())

    sink: list[str] = []
    events = []
    async for ev in engine.reason_stream(
        user_message="hi",
        system_prompt="sys",
        reasoning_prompt="reason",
        response_prompt="respond",
        context=_ctx(),
        patient_ids=["p1"],
        tier=ReasoningTier.BASIC,
        delta_sink=sink,
    ):
        events.append(ev)

    done = [e for e in events if isinstance(e, SSEDonePayload)]
    assert done, f"no done payload; events={events[:5]}"
    # sink mirrors RAW deltas (markers included) for disconnect salvage
    assert "".join(sink) == "Hello [[BUBBLE]]world [[AWAIT:meal]]"
    # visible tokens never carry markers
    text_events = "".join(e for e in events if isinstance(e, str))
    assert "[[AWAIT" not in text_events and "[[BUBBLE]]" not in text_events
    # raw response (with markers) reaches the done payload for processing
    assert "[[AWAIT:meal]]" in (done[0].data or {}).get("full_response", "")


@pytest.mark.asyncio
async def test_engine_stream_real_path_works_without_sink():
    gw = _streaming_gateway(["Just text."])
    engine = ReasoningEngine(gateway=gw, tool_executor=_tools())
    events = [ev async for ev in engine.reason_stream(
        user_message="hi", system_prompt="s", reasoning_prompt="r",
        response_prompt="p", context=_ctx(), patient_ids=["p1"],
        tier=ReasoningTier.BASIC,
    )]
    assert any(isinstance(e, SSEDonePayload) for e in events)
    assert not any("stream_error" in e for e in events if isinstance(e, str))


@pytest.mark.asyncio
async def test_engine_stream_no_silent_stream_error():
    """The regression this file exists for: a NameError inside the real
    responder loop surfaced to users as 'The response was interrupted'
    while every mocked-stream test stayed green."""
    gw = _streaming_gateway(["token"])
    engine = ReasoningEngine(gateway=gw, tool_executor=_tools())
    sink: list[str] = []
    events = [ev async for ev in engine.reason_stream(
        user_message="hi", system_prompt="s", reasoning_prompt="r",
        response_prompt="p", context=_ctx(), patient_ids=["p1"],
        tier=ReasoningTier.BASIC, delta_sink=sink,
    )]
    errors = [e for e in events if isinstance(e, str) and "stream_error" in e]
    assert not errors, f"real streaming path raised internally: {errors}"
    assert sink == ["token"]


@pytest.mark.asyncio
async def test_coordinator_stream_real_path():
    """Multi-domain streaming — the path where 'delta_sink is not defined'
    reached production while every mocked test stayed green."""
    from lib.ai_foundation.agents.health_query.coordinator import Coordinator

    gw = _streaming_gateway(["Multi ", "domain ", "answer."])

    specialist_result = MagicMock()
    specialist_result.findings = "glucose stable"
    specialist_result.cost_usd = 0.0
    specialist_result.tools_called = 0
    specialist_result.evidence = []
    specialist = MagicMock()
    specialist.investigate = AsyncMock(return_value=specialist_result)

    coord = Coordinator(
        gateway=gw,
        tool_executor=_tools(),
        specialists={"glucose": specialist, "meals": specialist},
    )

    sink: list[str] = []
    events = [ev async for ev in coord.orchestrate_stream(
        user_message="overview please",
        system_prompt="s", reasoning_prompt="r", response_prompt="p",
        context=_ctx(), patient_ids=["p1"],
        domains=["glucose", "meals"], tier=ReasoningTier.STANDARD,
        delta_sink=sink,
    )]

    errors = [e for e in events if isinstance(e, str) and "stream_error" in e]
    assert not errors, f"coordinator streaming raised internally: {errors}"
    assert any(isinstance(e, SSEDonePayload) for e in events)
    assert "".join(sink) == "Multi domain answer."


def test_delta_sink_always_declared_in_scope():
    """Static guard for the exact bug class: a name used inside a shared
    core generator but only added to the public wrapper's signature."""
    import ast

    for path in (
        "lib/ai_foundation/agents/health_query/reasoning_engine.py",
        "lib/ai_foundation/agents/health_query/coordinator.py",
    ):
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            uses = any(isinstance(n, ast.Name) and n.id == "delta_sink" for n in ast.walk(node))
            if not uses:
                continue
            params = {a.arg for a in node.args.kwonlyargs} | {a.arg for a in node.args.args}
            assert "delta_sink" in params, (
                f"{path}::{node.name} uses delta_sink without declaring it"
            )
