"""Care Intent structurer — one provider sentence → StructuredCareIntent.

Single gateway.extract call. The provider types natural language; every
structured field is inferred here and shown back for confirmation — the
provider never fills a form. The safety gate runs in the same call: clinical
orders (dosing, start/stop medication, diagnoses) are flagged, never stored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lib.ai_foundation.care_intents.contracts import (
    IntentCadence,
    IntentDomain,
    IntentType,
    StructuredCareIntent,
)
from lib.ai_foundation.models.registry import ModelTask

if TYPE_CHECKING:
    from lib.ai_foundation.models.gateway import ModelGateway

_INTENT_TYPES = ", ".join(t.value for t in IntentType)
_DOMAINS = ", ".join(d.value for d in IntentDomain)
_CADENCES = ", ".join(c.value for c in IntentCadence)

_SYSTEM_PROMPT = f"""You structure a care provider's instruction about a patient into a typed Care Intent for a health companion app.

The instruction is a free-text sentence like "keep reminding him to walk after dinner" or "watch her morning readings, I adjusted the dose Tuesday".

Fill every field:
- intent_type: one of {_INTENT_TYPES}
- domain: one of {_DOMAINS}
- trigger_condition: WHEN this matters, as a plain condition ("no walk logged within 2 hours after dinner"). null for passive context.
- cadence: one of {_CADENCES} — "daily" only when the provider clearly wants recurring reminders; "event" when tied to a data event; otherwise "passive".
- patient_summary: ONE warm, plain sentence the patient will read describing this focus area. No clinical jargon, no commands — supportive framing.
- success_criteria: only if the provider implied a measurable bar, else null.
- review_days: how long this should run before the provider reviews it (default 14; use the provider's stated duration when given).

SAFETY GATE — set safety_flag=true (with safety_reason) when the instruction:
- changes, starts, or stops a medication or its dose ("double his metformin if high")
- gives a diagnosis or orders a clinical test
- belongs in a prescription or clinical order, not a lifestyle nudge
Lifestyle guidance (food, movement, sleep, logging, monitoring awareness) is NOT flagged. Reminding a patient to take an already-prescribed medication as prescribed is NOT flagged; changing how they take it IS.
"""


async def structure_care_intent(
    gateway: ModelGateway,
    provider_text: str,
    *,
    trace_id: str | None = None,
) -> StructuredCareIntent:
    """Structure the provider's sentence. Raises on gateway failure — the
    caller (API edge) surfaces that as a retryable error, never stores a
    half-structured intent."""
    structured, _ = await gateway.extract(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": provider_text.strip()},
        ],
        response_model=StructuredCareIntent,
        task=ModelTask.CLASSIFICATION,
        trace_id=trace_id,
    )
    return structured
