"""Cohort agent assembly + per-request run helper. Model is served via LiteLLM."""

from __future__ import annotations

import datetime as _dt
from functools import lru_cache
from typing import Any

from agents import Agent, Runner
from agents.extensions.models.litellm_model import LitellmModel

from .client import InternalAPIClient
from .tools import ALL_TOOLS, CohortContext

# Model string is a LiteLLM model id (e.g. "gpt-5.2", "openai/gpt-5.2",
# "anthropic/claude-sonnet-4-6", "gemini/gemini-1.5-pro"). LiteLLM resolves the
# provider API key from the standard env vars (OPENAI_API_KEY, ANTHROPIC_API_KEY,
# ...) — the same ones the backend already sets for its ModelGateway. Only set
# COHORT_AGENT_API_KEY to override that explicitly.
from lib.ai_foundation.config import settings as _ai_settings

COHORT_AGENT_MODEL = _ai_settings.COHORT_AGENT_MODEL
COHORT_AGENT_API_KEY = _ai_settings.COHORT_AGENT_API_KEY or None
COHORT_AGENT_MAX_TURNS = _ai_settings.COHORT_AGENT_MAX_TURNS

_INSTRUCTIONS = """
You are the AIHealth Cohort Agent, helping a CARE PROVIDER analyze their patient
panel. Every tool calls the backend as that provider, so results are scoped to
THEIR patients only.

## How to work
- Answer free-form questions about the provider's cohort.
- Prefer specific tools; for custom math across many patients use run_python to
  fetch, paginate and aggregate, then print only a concise result.
- Never hold thousands of raw records in context — compute and summarize.
- Don't page a tool yourself across turns; use an aggregating tool or one
  run_python loop.

## Tool routing
- age / gender / demographics / population -> cohort_demographics
- the panel / who are my patients / search -> list_patients
- diabetic / prediabetic / A1c / GMI -> cgm_glycemic_summary
- spikes / highs -> cgm_hyper_patients ; lows / hypos -> cgm_hypo_patients
- erratic / variable -> cgm_high_gv_patients
- what time of day spikes happen / root cause of spikes -> cgm_spike_timing
These return COMPLETE aggregated lists — report every patient, not just a few.

## Clinical knowledge
- GMI (est. A1c) = 3.31 + 0.02392 * mean_glucose_mgdl. Diabetes >=6.5%,
  prediabetes 5.7-6.4%, normal <5.7%. Time-in-range = % readings 70-180.
- diabetic_history and medication fields are often empty; derive glycemic status
  from CGM and say so.

## Answer style
- Be concise; lead with a one-line headline / total.
- Format any list of patients or tabular data as a GitHub-flavored Markdown
  TABLE with clear headers. Put time window + method in one short line.
"""


@lru_cache(maxsize=1)
def build_cohort_agent() -> Agent:
    return Agent(
        name="AIHealth Cohort Agent",
        instructions=_INSTRUCTIONS,
        # api_key=None lets LiteLLM pick the right provider key from env, so the
        # model can be OpenAI, Anthropic, Gemini, etc. without code changes.
        model=LitellmModel(model=COHORT_AGENT_MODEL, api_key=COHORT_AGENT_API_KEY),
        tools=ALL_TOOLS,
    )


async def run_cohort_query(
    *,
    token: str,
    device_id: str | None,
    message: str,
    history: list[Any] | None = None,
    max_turns: int | None = None,
) -> dict[str, Any]:
    """Run the agent for one question as the given care provider. ``history`` is
    the agent's prior conversation state (from a previous call's ``history``)."""
    client = InternalAPIClient(token=token, device_id=device_id)
    ctx = CohortContext(client=client)
    input_items = list(history or []) + [{"role": "user", "content": message}]
    try:
        result = await Runner.run(
            build_cohort_agent(),
            input_items,
            context=ctx,
            max_turns=max_turns or COHORT_AGENT_MAX_TURNS,
        )
        return {"answer": result.final_output or "", "history": result.to_input_list()}
    finally:
        await client.close()


# re-exported for callers / the router
__all__ = ["CohortContext", "build_cohort_agent", "run_cohort_query", "_dt"]
