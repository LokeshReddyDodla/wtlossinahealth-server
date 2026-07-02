"""Assemble a HealthQueryAgent for evals: real LLMs, fixture data.

Real: ModelGateway (live provider calls), PromptRegistry (local .md files),
ReasoningEngine, planner, reflector, coordinator + specialists.
Fake: retrieval, memory, name resolution, insights, metabolic profile.
No persistence / fact extraction — nothing writes anywhere.
"""

from __future__ import annotations

from typing import Any

from lib.ai_foundation.agents.core.context_loader import ContextLoader
from lib.ai_foundation.agents.health_query import HealthQueryAgent
from lib.ai_foundation.agents.health_query.coordinator import Coordinator
from lib.ai_foundation.agents.health_query.planner import InvestigationPlanner
from lib.ai_foundation.agents.health_query.reasoning_engine import ReasoningEngine
from lib.ai_foundation.agents.health_query.reflector import ReflectionEngine
from lib.ai_foundation.agents.health_query.specialists import (
    DOCUMENTS_SPEC,
    FITNESS_SPEC,
    GLUCOSE_SPEC,
    NUTRITION_SPEC,
    SLEEP_SPEC,
    Specialist,
    VITALS_SPEC,
)
from lib.ai_foundation.agents.health_query.tools import ToolExecutor
from lib.ai_foundation.events.bus import EventBus
from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import build_default_registry
from lib.ai_foundation.prompts.registry import PromptRegistry

from .fixtures import (
    FakeInsightTracker,
    FakeMemory,
    FakeMetabolicService,
    FakeResolver,
    FixtureRetriever,
)

_gateway: ModelGateway | None = None


def shared_gateway() -> ModelGateway:
    """One gateway per eval run — reused by the agent factory and the judge."""
    global _gateway
    if _gateway is None:
        _gateway = ModelGateway(registry=build_default_registry())
    return _gateway


def build_eval_agent(
    records: list[dict[str, Any]],
    facts: list | None = None,
) -> HealthQueryAgent:
    gateway = shared_gateway()
    retriever = FixtureRetriever(records)
    memory = FakeMemory(facts)
    resolver = FakeResolver()
    tracker = FakeInsightTracker()

    tools = ToolExecutor(
        qdrant=retriever,
        insight_tracker=tracker,
        patient_resolver=resolver,
        metabolic_service=FakeMetabolicService(),
    )
    planner = InvestigationPlanner(gateway=gateway)
    reflector = ReflectionEngine(gateway=gateway)
    engine = ReasoningEngine(
        gateway=gateway,
        tool_executor=tools,
        planner=planner,
        reflector=reflector,
    )
    specialists = {
        "glucose": Specialist(domain_spec=GLUCOSE_SPEC, gateway=gateway, tool_executor=tools),
        "nutrition": Specialist(domain_spec=NUTRITION_SPEC, gateway=gateway, tool_executor=tools),
        "fitness": Specialist(domain_spec=FITNESS_SPEC, gateway=gateway, tool_executor=tools),
        "vitals": Specialist(domain_spec=VITALS_SPEC, gateway=gateway, tool_executor=tools),
        "sleep": Specialist(domain_spec=SLEEP_SPEC, gateway=gateway, tool_executor=tools),
        "documents": Specialist(domain_spec=DOCUMENTS_SPEC, gateway=gateway, tool_executor=tools),
    }
    coordinator = Coordinator(
        gateway=gateway,
        tool_executor=tools,
        planner=planner,
        reflector=reflector,
        specialists=specialists,
    )
    context_loader = ContextLoader(
        memory=memory,
        patient_resolver=resolver,
        insight_tracker=tracker,
        retriever=retriever,
    )
    return HealthQueryAgent(
        gateway=gateway,
        memory=memory,
        prompts=PromptRegistry(),  # local .md prompts via _ensure_prompts
        event_bus=EventBus(),
        context_loader=context_loader,
        reasoning_engine=engine,
        coordinator=coordinator,
        persistence=None,      # evals never write
        fact_extractor=None,
    )
