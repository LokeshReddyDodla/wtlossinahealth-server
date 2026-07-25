"""Care-team coordination brains: conflict detection + AI-proposed intents.

Both are advisory. Conflicts warn the creating provider — the system never
silently decides which clinician wins. Proposals return dry-run sentences
for the provider to approve via the normal create flow — nothing is stored
here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from lib.ai_foundation.models.registry import ModelTask

if TYPE_CHECKING:
    from lib.ai_foundation.models.gateway import ModelGateway

_CONFLICT_PROMPT = """A care provider is adding a new instruction for a patient. Compare it against the patient's EXISTING care-team instructions.

Report a conflict ONLY when following both would genuinely contradict — opposite behaviors, incompatible timing, or one undoes the other (e.g. "add a bedtime snack" vs "no food after 9 PM"). Overlap or redundancy is NOT a conflict. Different domains almost never conflict.

For each real conflict, write one plain sentence naming the other provider and the tension. No conflicts → empty list."""


class ConflictReport(BaseModel):
    conflicts: list[str] = Field(default_factory=list)


async def detect_intent_conflicts(
    gateway: ModelGateway,
    *,
    new_text: str,
    existing: list[dict],
    trace_id: str | None = None,
) -> list[str]:
    """Warnings like 'Dr. Mehta's "no food after 9 PM" conflicts with a bedtime snack.'"""
    if not existing:
        return []
    existing_lines = "\n".join(
        f"- [{ci['author_name']}, {ci['author_role']}] {ci['original_text']}"
        for ci in existing
    )
    report, _ = await gateway.extract(
        messages=[
            {"role": "system", "content": _CONFLICT_PROMPT},
            {"role": "user", "content": f"NEW INSTRUCTION:\n{new_text}\n\nEXISTING INSTRUCTIONS:\n{existing_lines}"},
        ],
        response_model=ConflictReport,
        task=ModelTask.CLASSIFICATION,
        trace_id=trace_id,
    )
    return report.conflicts


_PROPOSE_PROMPT = """You help a care provider decide what the health platform should focus on for one patient, based on the patient's recent AI-generated health insights.

Propose 0-2 care instructions the PROVIDER could give — each as one natural sentence the provider might say ("keep reminding her to...", "watch his..."). Rules:
- Ground every proposal in a pattern visible in the insights; cite it in the rationale.
- Never propose medication/dosing changes or anything clinical — lifestyle, logging, and monitoring focus only.
- Skip anything the existing instructions already cover.
- No pattern worth acting on → propose nothing. An empty list is a good answer."""


class IntentProposal(BaseModel):
    text: str = Field(description="The instruction, phrased as the provider would say it.")
    rationale: str = Field(description="The data pattern that motivates it, one sentence.")


class IntentProposals(BaseModel):
    proposals: list[IntentProposal] = Field(default_factory=list)


async def propose_intents(
    gateway: ModelGateway,
    *,
    recent_insights: list[dict],
    existing: list[dict],
    trace_id: str | None = None,
) -> list[IntentProposal]:
    """0-2 grounded proposals from recent monitor insights. Never stored —
    the provider approves via the normal create flow (dry_run → create)."""
    if not recent_insights:
        return []
    insight_lines = "\n".join(
        f"- [{i.get('severity', 'info')}] {i.get('title', '')}: {i.get('message', i.get('body', ''))}"
        for i in recent_insights
    )
    existing_lines = "\n".join(
        f"- {ci['original_text']}" for ci in existing
    ) or "(none)"
    result, _ = await gateway.extract(
        messages=[
            {"role": "system", "content": _PROPOSE_PROMPT},
            {"role": "user", "content": (
                f"RECENT INSIGHTS (newest first):\n{insight_lines}\n\n"
                f"EXISTING CARE-TEAM INSTRUCTIONS:\n{existing_lines}"
            )},
        ],
        response_model=IntentProposals,
        task=ModelTask.CLASSIFICATION,
        trace_id=trace_id,
    )
    return result.proposals[:2]
