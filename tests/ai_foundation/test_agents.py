"""Tests for Agent Framework — state models and BaseAgent."""

import pytest

from lib.ai_foundation.agents.state import (
    AgentContext,
    AgentInput,
    AgentOutput,
    RequestPriority,
)
from lib.ai_foundation.agents.base import BaseAgent


class TestAgentState:
    def test_agent_context_defaults(self):
        ctx = AgentContext()
        assert ctx.user_role == "patient"
        assert ctx.priority == RequestPriority.NORMAL
        assert ctx.patient_ids == []

    def test_agent_context_care_provider(self):
        ctx = AgentContext(
            user_id="u1",
            user_role="care_provider",
            priority=RequestPriority.HIGH,
            patient_ids=["p1", "p2", "p3"],
        )
        assert ctx.user_role == "care_provider"
        assert len(ctx.patient_ids) == 3

    def test_agent_input(self):
        inp = AgentInput(
            message="How were my sugars?",
            context=AgentContext(patient_id="p1"),
            stream=True,
        )
        assert inp.message == "How were my sugars?"
        assert inp.stream is True
        assert inp.context.patient_id == "p1"

    def test_agent_output(self):
        out = AgentOutput(
            message="Your glucose was stable at 120 mg/dL.",
            is_ready=True,
            suggestions=[{"label": "Details", "description": "Show me the details"}],
            trace_id="trc_abc",
            cost_usd=0.005,
            latency_ms=2100,
            model_id="gpt-5.1",
        )
        assert out.is_ready is True
        assert out.cost_usd == 0.005
        assert len(out.suggestions) == 1


class TestRequestPriority:
    def test_priority_values(self):
        assert RequestPriority.CRITICAL.value == "critical"
        assert RequestPriority.HIGH.value == "high"
        assert RequestPriority.NORMAL.value == "normal"
        assert RequestPriority.LOW.value == "low"


class TestBaseAgent:
    def test_base_agent_raises_not_implemented(self):
        class BareAgent(BaseAgent):
            agent_id = "bare"

        # Can't test async directly without gateway, but verify class structure
        agent = BareAgent(gateway=None)
        assert agent.agent_id == "bare"

    @pytest.mark.asyncio
    async def test_run_not_implemented(self):
        class BareAgent(BaseAgent):
            agent_id = "bare"

        agent = BareAgent(gateway=None)
        with pytest.raises(NotImplementedError, match="must implement run"):
            await agent.run(AgentInput(message="test"))

    def test_repr(self):
        class MyAgent(BaseAgent):
            agent_id = "my_agent"

        agent = MyAgent(gateway=None)
        assert "my_agent" in repr(agent)

    def test_services_injected(self):
        class TestAgent(BaseAgent):
            agent_id = "test"

        agent = TestAgent(
            gateway="fake_gateway",
            memory="fake_memory",
            prompts="fake_prompts",
            event_bus="fake_bus",
        )
        assert agent.gateway == "fake_gateway"
        assert agent.memory == "fake_memory"
        assert agent.prompts == "fake_prompts"
        assert agent.event_bus == "fake_bus"

    @pytest.mark.asyncio
    async def test_custom_agent_run(self):
        class EchoAgent(BaseAgent):
            agent_id = "echo"

            async def run(self, input: AgentInput) -> AgentOutput:
                return AgentOutput(
                    message=f"Echo: {input.message}",
                    trace_id="trc_echo",
                )

        agent = EchoAgent(gateway=None)
        result = await agent.run(AgentInput(message="hello"))
        assert result.message == "Echo: hello"
        assert result.trace_id == "trc_echo"
