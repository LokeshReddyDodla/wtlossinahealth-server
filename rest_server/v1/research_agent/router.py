"""Research Agent — FastAPI router.

Routes:
    POST /research-agent/query   — SSE streaming cohort question (Modes 1 & 2)

Phase 2 will add:
    POST /research-agent/query/sync          — non-streaming variant
    POST /research-agent/cohorts             — save a cohort
    GET  /research-agent/cohorts/{cohort_id} — resolve a saved cohort

Phase 3 will add:
    POST /research-agent/job        — kick off Cohort Deep Dive (Mode 3)
    GET  /research-agent/job/{id}   — poll status + retrieve results
"""

from fastapi import APIRouter

router = APIRouter(prefix="/research-agent", tags=["V1 - Research Agent"])

from .query import *  # noqa: E402, F401, F403  -- registers endpoints onto router
