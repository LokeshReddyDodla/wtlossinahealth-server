"""Grounding verification — a self-check gate on the responder's output.

Prompt guardrails reduce but cannot GUARANTEE data integrity: across full eval
runs the responder still occasionally fabricates a patient number/event,
confirms a false patient claim, or disavows real data under challenge. For a
health agent that is a safety issue, so the final answer gets verified against
the evidence it was built from before it ships:

    responder → verify_grounding(response, evidence) → (if ungrounded) correct once

The verifier is an LLM check (structured output) with the SAME
fabrication-vs-inference rules the eval judge uses, so production and eval agree
on what "grounded" means. It catches three failure modes:
  * ungrounded_claims  — asserts patient data not in the evidence (#5, #3)
  * wrongly_denied     — denies / calls fabricated data that IS in evidence (#1)
General medical knowledge and hedged inferences are NOT violations.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask

logger = logging.getLogger(__name__)


class GroundingVerdict(BaseModel):
    """Structured verdict on whether a reply is faithful to its evidence."""

    ungrounded_claims: list[str] = Field(
        default_factory=list,
        description=(
            "Claims about THE PATIENT'S OWN DATA (their readings, meals, events, "
            "history) asserted as fact but NOT present in and NOT computable from "
            "the evidence — including a patient's own claim the assistant echoed as "
            "confirmed (e.g. confirming a '300 reading' that isn't in the data). "
            "General medical knowledge, arithmetic on evidence numbers, and hedged "
            "inferences ('likely', 'might') that cite evidence are NOT violations."
        ),
    )
    wrongly_denied: list[str] = Field(
        default_factory=list,
        description=(
            "Data that IS in the evidence but the reply denies, omits as absent, or "
            "calls fabricated/made-up (e.g. 'I don't have any spike data' when a "
            "rapid_spike_event is in the evidence). Telling a patient their real "
            "data isn't there is as harmful as inventing data."
        ),
    )
    reasoning: str = Field(description="1-2 sentences.")

    @property
    def grounded(self) -> bool:
        return not self.ungrounded_claims and not self.wrongly_denied


_VERIFY_SYSTEM = """You verify a diabetes-care assistant's reply against the COMPLETE data it was given. You are a strict, literal checker — not a stylist.

Return two lists:
1. ungrounded_claims — statements about THE PATIENT'S OWN DATA (specific readings, meals, events, dates, patterns) asserted as fact that are NOT in the evidence and NOT directly computable from it. This INCLUDES a patient's own assertion the reply treated as confirmed fact (a reading, a food) when it isn't in the evidence.
2. wrongly_denied — data that IS in the evidence but the reply denies exists, says it doesn't have, or calls fabricated/made-up.

NOT violations (never list these):
- General medical / self-care knowledge (hypo first aid, how meds work, physiology).
- Arithmetic derived from evidence numbers (sums, averages, ranges, differences).
- Hedged inferences that cite evidence ("the peanuts likely slowed absorption").
- The patient's SUBJECTIVE experience (how they felt, what they say they did) — only a specific NUMBER or logged EVENT must match the evidence.

Be literal and conservative: only list a claim you are confident is false-about-the-data or a denial of data that is genuinely present. If the reply is faithful, return empty lists."""


async def verify_grounding(
    gateway: ModelGateway, *, response: str, evidence_text: str,
) -> GroundingVerdict:
    """Check ``response`` against ``evidence_text``; empty lists = grounded."""
    if not response.strip() or not evidence_text.strip():
        return GroundingVerdict(reasoning="nothing to verify")
    verdict, _ = await gateway.extract(
        messages=[
            {"role": "system", "content": _VERIFY_SYSTEM},
            {"role": "user", "content": (
                f"## Evidence the assistant had (COMPLETE)\n{evidence_text}\n\n"
                f"## Assistant reply to verify\n{response}"
            )},
        ],
        response_model=GroundingVerdict,
        task=ModelTask.QUALITY_JUDGE,
    )
    return verdict


def build_correction(verdict: GroundingVerdict) -> str:
    """A system instruction telling the responder exactly what to fix, for a
    single regeneration. Only called when the verdict is not grounded."""
    parts = ["Your draft reply had grounding errors. Rewrite it, same intent and tone, fixing ONLY these:"]
    if verdict.ungrounded_claims:
        parts.append(
            "- Remove or correct these claims — they are NOT in the patient's data "
            "(never state patient data you don't have; don't confirm a number/event "
            "the patient asserted if it isn't in the data):\n  - "
            + "\n  - ".join(verdict.ungrounded_claims)
        )
    if verdict.wrongly_denied:
        parts.append(
            "- This data IS in the patient's records — do NOT deny it or call it "
            "fabricated; state it plainly:\n  - "
            + "\n  - ".join(verdict.wrongly_denied)
        )
    return "\n".join(parts)
