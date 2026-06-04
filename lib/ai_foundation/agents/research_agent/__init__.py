"""
Research Agent — cohort-scale provider analytics.

Sibling to ``health_query``. Where ``health_query`` is built for one patient
at a time, ``research_agent`` is built for cohort-scale questions across tens
to thousands of patients: aggregate counts, multi-criterion intersection,
ranking, and (future) per-patient research extraction.

The agent never stuffs raw records into the LLM context. It plans the
question into a structured ``CohortSpec``, executes it against the cheapest
available backend (Qdrant aggregations, scorecards when present, Mongo
intersection), and the LLM only ever sees small results to narrate.

Public surface:

    from lib.ai_foundation.agents.research_agent import ResearchAgent
    from lib.ai_foundation.agents.research_agent.contracts import (
        ResearchInput, ResearchOutput, CohortRef, CohortSpec,
    )

Phase 1 ships Modes 1 (Cohort Insights) and 2 (Cohort Brief). Mode 3
(Cohort Deep Dive) requires Anthropic Batches API support in the gateway
and is deferred. See ``docs/internal/research_agent_plan.md`` and
``docs/internal/research_agent_architecture.md`` for the full design.
"""

from __future__ import annotations

from .agent import ResearchAgent
from .contracts import (
    CohortRef,
    CohortRefKind,
    CohortSpec,
    Criterion,
    ExecutionResult,
    FunnelStep,
    HistoryTurn,
    ResearchInput,
    ResearchOutput,
)

__all__ = [
    "ResearchAgent",
    "ResearchInput",
    "ResearchOutput",
    "CohortRef",
    "CohortRefKind",
    "CohortSpec",
    "Criterion",
    "FunnelStep",
    "ExecutionResult",
    "HistoryTurn",
]
