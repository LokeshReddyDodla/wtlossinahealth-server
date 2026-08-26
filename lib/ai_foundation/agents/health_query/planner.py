"""
Investigation Planner — generates a structured plan before the reasoning loop.

Instead of discovering data needs round-by-round, the thinker thinks holistically
first: what to fetch, in what order, and why. Phase 1 steps execute in parallel.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from lib.ai_foundation.config import settings
from lib.ai_foundation.models.gateway import safe_cost
from lib.ai_foundation.models.registry import ModelTask

if TYPE_CHECKING:
    from lib.ai_foundation.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


# ── Plan Models ────────────────────────────────────────────────────────────


class PlanStep(BaseModel):
    """A single step in the investigation plan."""

    tool_name: str = Field(description="Tool to call: look_up, investigate_day, compare_baseline, or find_patterns.")
    arguments: dict[str, Any] = Field(description="Arguments to pass to the tool.")
    reason: str = Field(description="Why this step is needed, in one sentence.")
    phase: int = Field(
        description=(
            "Execution phase. Phase 1 = initial data fetch (can run in parallel). "
            "Phase 2 = follow-up based on Phase 1 results. "
            "Phase 3 = correlation and pattern verification."
        ),
    )


class InvestigationPlan(BaseModel):
    """Structured investigation plan generated before executing."""

    strategy: str = Field(
        description=(
            "User-facing, first-person summary of the investigation approach. "
            "Narrate what you will do; never phrase it as an instruction to the user."
        ),
    )
    steps: list[PlanStep] = Field(description="Ordered list of tool calls to execute.")
    domains_involved: list[str] = Field(
        default_factory=list,
        description="Health domains involved: glucose, nutrition, fitness, profile, etc.",
    )


# ── Planner ────────────────────────────────────────────────────────────────


class InvestigationPlanner:
    """Generates investigation plans via a single LLM call.

    The planner produces a structured plan that groups tool calls into phases:
    - Phase 1: Initial data fetching (can run in parallel)
    - Phase 2: Follow-up investigation based on Phase 1 results
    - Phase 3: Correlation and pattern verification
    """

    def __init__(self, *, gateway: ModelGateway) -> None:
        self._gateway = gateway

    async def plan(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        planning_prompt: str,
        model_id: str,
        trace_id: str | None = None,
    ) -> tuple[InvestigationPlan, float]:
        """Generate an investigation plan.

        Args:
            messages: Current conversation (system + context + user question).
            tool_schemas: Available tool definitions.
            planning_prompt: The planning system prompt.
            model_id: Model to use for planning (thinker model).

        Returns:
            Tuple of (plan, cost_usd).
        """
        # Build planning-specific messages
        plan_messages: list[dict[str, Any]] = list(messages)  # copy

        # Insert planning prompt and tool descriptions
        tool_desc = self._format_tool_descriptions(tool_schemas)
        plan_messages.insert(1, {
            "role": "system",
            "content": f"{planning_prompt}\n\nAvailable tools:\n{tool_desc}",
        })

        plan, meta = await self._gateway.extract(
            messages=plan_messages,
            response_model=InvestigationPlan,
            task=ModelTask.CLASSIFICATION,
            model_id=model_id,
            timeout=settings.PLANNING_TIMEOUT_SECONDS,
            trace_id=trace_id,
        )

        cost = safe_cost(meta)

        logger.debug(
            "Investigation plan: %s (%d steps, phases: %s, cost=%.5f)",
            plan.strategy, len(plan.steps),
            sorted({s.phase for s in plan.steps}),
            cost,
        )

        return plan, cost

    @staticmethod
    def _format_tool_descriptions(schemas: list[dict[str, Any]]) -> str:
        """Format tool schemas into readable text for the planning prompt."""
        lines: list[str] = []
        for schema in schemas:
            func = schema.get("function", {})
            name = func.get("name", "unknown")
            desc = func.get("description", "")
            params = func.get("parameters", {}).get("properties", {})
            param_names = ", ".join(params.keys())
            short_desc = desc[:150] + ("..." if len(desc) > 150 else "")
            lines.append(f"- **{name}**({param_names}): {short_desc}")
        return "\n".join(lines)
