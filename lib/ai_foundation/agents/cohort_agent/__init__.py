"""Cohort Agent — a flexible, tool-calling research agent over the care
provider's patient panel.

Unlike ``research_agent`` (structured plan -> execute over Qdrant), this agent
uses an open-ended OpenAI-Agents-SDK loop with bounded data tools that read the
existing /dashboard/metrics and /v1 endpoints, plus a ``run_python`` sandbox for
ad-hoc computation. The model is served through LiteLLM, so it routes to
whichever provider the backend is configured for.

Public surface:
    build_cohort_agent() -> Agent
    CohortContext(client=...)            # per-request auth, passed to Runner.run
"""

from .agent import CohortContext, build_cohort_agent, run_cohort_query

__all__ = ["CohortContext", "build_cohort_agent", "run_cohort_query"]
