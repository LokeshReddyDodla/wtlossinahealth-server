"""Adherence evaluator — did the asked behavior happen on a completed day?

One extract call per patient-day covering ALL active intents at once,
reusing the data the monitor's morning scan already fetched (the previous,
complete day) — no extra retrieval, no premature intra-day verdicts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from lib.ai_foundation.models.registry import ModelTask

if TYPE_CHECKING:
    from lib.ai_foundation.models.gateway import ModelGateway

_SYSTEM_PROMPT = """You evaluate whether a patient followed their care team's instructions on ONE completed day, using only that day's logged health data.

For EVERY numbered instruction, return one verdict:
- "followed" — the data shows the asked behavior happened (or the thing to avoid was avoided).
- "missed" — the data shows it did not happen, or clearly contradicts the instruction.
- "unclear" — the data cannot tell (nothing relevant logged, instruction is passive/observational, or coverage is too thin). When in doubt, "unclear" — never guess "missed" from absence of data alone unless the instruction is specifically about logging.

barrier_note: ONLY when the day's data or the patient's own words (PATIENT CONTEXT) show a likely reason for a miss — a symptom entry, an unusual schedule, no data after a certain hour, or something the patient told the assistant ("knee pain makes walking hard"). One short factual phrase, no speculation. null otherwise.

The day's data may be TRUNCATED (heavy loggers get capped records). For "restrict" style instructions, absence of a violating record in truncated data is NOT proof it was followed — prefer "unclear" when coverage looks partial.

Instructions are numbered starting at 1. Return a verdict for every instruction index, in any order."""


class IntentVerdict(BaseModel):
    intent_index: int = Field(description="Index of the instruction being judged (as numbered in the input).")
    status: Literal["followed", "missed", "unclear"]
    barrier_note: str | None = None


class AdherenceVerdicts(BaseModel):
    verdicts: list[IntentVerdict] = Field(default_factory=list)


async def evaluate_adherence(
    gateway: ModelGateway,
    *,
    intents: list[dict],
    day_data_text: str,
    day_label: str,
    patient_context: str = "",
) -> list[dict]:
    """Judge each intent against one completed day's data.

    ``intents`` rows need ``care_intent_id`` + ``original_text`` (+ optional
    ``trigger_condition``). Returns ``{care_intent_id, status, note}`` dicts;
    intents the model skips default to "unclear" so a day is never silently
    unrecorded.
    """
    if not intents:
        return []

    numbered = "\n".join(
        f"{i}. {ci['original_text']}"
        + (f" (relevant when: {ci['trigger_condition']})" if ci.get("trigger_condition") else "")
        for i, ci in enumerate(intents, start=1)
    )
    user_msg = (
        f"INSTRUCTIONS:\n{numbered}\n\n"
        f"DATA FOR {day_label} (complete day):\n{day_data_text or '(no data logged)'}"
    )
    if patient_context:
        # Memory carries what the patient TOLD the assistant (chat) — the
        # barrier channel logged data can't see.
        user_msg += f"\n\nPATIENT CONTEXT (from the patient's own words):\n{patient_context}"

    result, _ = await gateway.extract(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_model=AdherenceVerdicts,
        task=ModelTask.CLASSIFICATION,
    )

    by_index = {v.intent_index: v for v in result.verdicts}
    out = []
    for i, ci in enumerate(intents, start=1):
        v = by_index.get(i)
        out.append({
            "care_intent_id": ci["care_intent_id"],
            "status": v.status if v else "unclear",
            "note": (v.barrier_note if v else None),
        })
    return out
