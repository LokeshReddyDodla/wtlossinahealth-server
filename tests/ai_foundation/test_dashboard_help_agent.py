"""Tests for the Dashboard Help agent — answer generation, video matching, history coercion.

Mocks the ModelGateway so no DB / network / real LLM is needed. The gateway's
``complete`` is dispatched by ``task`` so we can drive the answer call and the
video-picker classifier call independently.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lib.ai_foundation.agents.dashboard_help import DashboardHelpAgent
from lib.ai_foundation.agents.dashboard_help.video_catalog import (
    HELP_VIDEOS_BASE_URL,
    VIDEO_CATALOG,
    video_url,
)
from lib.ai_foundation.agents.state import AgentContext, AgentInput
from lib.ai_foundation.models.registry import ModelTask


def _response(content: str):
    """Minimal stand-in for the gateway's LLMResponse (content + cost + model_id)."""
    return SimpleNamespace(
        content=content,
        cost=SimpleNamespace(total_cost=0.0001),
        model_id="test-model",
    )


# Langfuse trace helpers are no-ops on the real gateway when disabled; the
# stub just needs them to exist so the agent can call them.
_LF = {
    "set_langfuse_context": lambda **k: None,
    "langfuse_trace_input": lambda **k: None,
    "langfuse_trace_output": lambda **k: None,
}


def _gateway(*, answer: str, video: str):
    """Gateway whose ``complete`` returns ``answer`` for RESPONSE_GENERATION and
    ``video`` (an id or NONE) for the CLASSIFICATION video-picker call."""

    async def complete(*, task, **_):
        if task == ModelTask.CLASSIFICATION:
            return _response(video)
        return _response(answer)

    return SimpleNamespace(complete=AsyncMock(side_effect=complete), **_LF)


def _agent(gateway) -> DashboardHelpAgent:
    return DashboardHelpAgent(gateway=gateway)


def _input(message: str, *, history=None) -> AgentInput:
    return AgentInput(
        message=message,
        context=AgentContext(user_id="u1", user_role="care_provider"),
        metadata={"history": history} if history is not None else {},
    )


@pytest.mark.asyncio
async def test_answer_attaches_matching_video():
    gw = _gateway(answer="1. Open the patient.\n2. Click Assign Package.", video="assign-package")
    out = await _agent(gw).run(_input("How do I assign a package to a patient?"))

    assert out.message.startswith("1. Open the patient.")
    assert out.data["video_id"] == "assign-package"
    assert out.data["video_url"] == f"{HELP_VIDEOS_BASE_URL}/assign-package.mp4"
    assert out.data["video_url"] == "https://user-assets.aihealth.clinic/help-videos/assign-package.mp4"
    assert out.trace_id


@pytest.mark.asyncio
async def test_off_topic_returns_no_video():
    gw = _gateway(answer="I can only help with using the dashboard.", video="NONE")
    out = await _agent(gw).run(_input("What's the weather today?"))

    assert out.data["video_id"] is None
    assert out.data["video_url"] is None


@pytest.mark.asyncio
async def test_picker_paraphrase_is_matched_substring():
    # Classifier may echo extra text/casing; agent should still extract the valid id.
    gw = _gateway(answer="Here's how.", video="Video: ADD-PATIENT")
    out = await _agent(gw).run(_input("how to add a new patient"))

    assert out.data["video_id"] == "add-patient"


@pytest.mark.asyncio
async def test_picker_unknown_id_yields_none():
    gw = _gateway(answer="Here's how.", video="not-a-real-clip")
    out = await _agent(gw).run(_input("something"))

    assert out.data["video_id"] is None


@pytest.mark.asyncio
async def test_malformed_history_is_dropped():
    gw = _gateway(answer="ok", video="NONE")
    history = [
        {"role": "user", "content": "valid earlier question"},
        {"role": "system", "content": "should be dropped"},  # wrong role
        {"role": "assistant", "content": ""},                 # empty content
        {"bogus": "shape"},                                   # not a turn
        "totally wrong",                                       # not a dict
    ]
    await _agent(gw).run(_input("follow up", history=history))

    # Inspect the messages passed to the answer (RESPONSE_GENERATION) call.
    answer_call = next(
        c for c in gw.complete.call_args_list
        if c.kwargs["task"] == ModelTask.RESPONSE_GENERATION
    )
    messages = answer_call.kwargs["messages"]
    roles = [m["role"] for m in messages]

    assert roles[0] == "system"           # brain injected first
    assert roles[-1] == "user"            # current message last
    history_msgs = messages[1:-1]
    assert history_msgs == [{"role": "user", "content": "valid earlier question"}]


@pytest.mark.asyncio
async def test_system_message_contains_knowledge_base():
    gw = _gateway(answer="ok", video="NONE")
    agent = _agent(gw)
    assert "KNOWLEDGE BASE" in agent._system_message
    await agent.run(_input("hi"))

    answer_call = next(
        c for c in gw.complete.call_args_list
        if c.kwargs["task"] == ModelTask.RESPONSE_GENERATION
    )
    assert answer_call.kwargs["messages"][0]["content"] == agent._system_message


@pytest.mark.asyncio
async def test_answer_failure_returns_graceful_message():
    async def boom(*, task, **_):
        if task == ModelTask.RESPONSE_GENERATION:
            raise RuntimeError("LLM down")
        return _response("NONE")

    gw = SimpleNamespace(complete=AsyncMock(side_effect=boom), **_LF)
    out = await _agent(gw).run(_input("anything"))

    assert out.is_ready is False
    assert "went wrong" in out.message.lower()


@pytest.mark.asyncio
async def test_video_pick_failure_does_not_break_answer():
    async def partial(*, task, **_):
        if task == ModelTask.CLASSIFICATION:
            raise RuntimeError("classifier down")
        return _response("the answer")

    gw = SimpleNamespace(complete=AsyncMock(side_effect=partial), **_LF)
    out = await _agent(gw).run(_input("how do I add a patient"))

    assert out.message == "the answer"
    assert out.data["video_id"] is None


def test_video_url_builder_matches_catalog():
    for vid in VIDEO_CATALOG:
        assert video_url(vid) == f"{HELP_VIDEOS_BASE_URL}/{vid}.mp4"
