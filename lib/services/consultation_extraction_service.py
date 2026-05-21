"""Extracts structured insights from a doctor-patient consultation transcript.

Single responsibility: transcript → structured JSON via ModelGateway.
Mirrors the shape of PrescriptionExtractionService.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.schemas.consultation import ExtractedConsultation

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are a clinical scribe. Given a transcript of a conversation between a \
doctor and a patient, extract the structured clinical information into the \
provided JSON schema.

Rules:
- Use ONLY information present in the transcript. Do not infer or invent.
- If a field is not discussed, set it to null (or an empty list for list fields).
- Speakers may not be labeled; use clinical context to decide what was said \
by whom.
- Transcripts may be noisy (mishearings, filler words, partial sentences). \
Skip clearly unintelligible fragments.

Field guidance:
- chief_complaint: the main reason the patient came in, in one short phrase.
- history_of_present_illness: onset, duration, severity, triggers, what makes \
it better/worse, associated symptoms — narrative form.
- past_history_mentioned: any past medical history the patient or doctor \
referenced (chronic conditions, surgeries, allergies). Null if nothing \
mentioned.
- examination_findings: anything the doctor states about vitals or physical \
exam during the conversation (e.g., "your BP is 140/90", "your throat looks red").
- assessment: the doctor's working diagnosis or impression.
- plan: the doctor's overall plan in narrative form (separate from medicines \
and investigations, which have their own fields).
- medicines: every medication the doctor prescribes during the conversation. \
For each medicine, follow the same dosing-schedule rules used elsewhere: \
"1-0-1" → morning + evening doses; "twice a day" → morning + evening; \
"once a day" → morning; "at bedtime"/"HS" → night; "SOS"/"PRN"/"as needed" \
→ is_sos=true with empty doses. For frequency: daily / OD / unspecified → \
schedule=null. "Every other day" / "QOD" → interval schedule with \
interval_days=2.
- investigations_ordered: lab tests, imaging, or other workup the doctor \
orders during the conversation. List each as a short phrase.
- lifestyle_advice: non-pharmacological advice the doctor gives (diet, sleep, \
exercise, hydration, etc.). Each as a short phrase.
- follow_up: when the doctor asks the patient to come back, in plain text \
(e.g., "1 week", "after lab results", "if symptoms worsen").
- red_flags: warning signs the doctor tells the patient to watch for. Each \
as a short phrase.
- summary: a 2-3 sentence overall summary of the visit, written for the \
careprovider dashboard.
"""


class ConsultationExtractionService:
    """Transcript → ExtractedConsultation via the model gateway."""

    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    async def extract(self, transcript: str) -> ExtractedConsultation:
        """Extract structured consultation data from a transcript."""
        trace_id = str(uuid4())
        self.gateway.langfuse_trace_input(
            trace_id=trace_id,
            name="consultation-extraction",
            input_text=transcript,
        )

        messages: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extract the structured clinical information from this "
                    "doctor-patient conversation transcript:\n\n"
                    f"{transcript}"
                ),
            },
        ]

        extracted, meta = await self.gateway.extract(
            messages=messages,
            response_model=ExtractedConsultation,
            task=ModelTask.STRUCTURED_ANALYSIS,
            model_id="gpt-4o",
            trace_id=trace_id,
        )

        cost = meta.usage.cost.total_cost if meta.usage else 0
        logger.info(
            "Consultation extracted: %d medicines, %d investigations, %dms, $%.4f",
            len(extracted.medicines),
            len(extracted.investigations_ordered),
            meta.latency_ms,
            cost,
        )

        self.gateway.langfuse_trace_output(
            trace_id=trace_id,
            output_text=(
                f"Extracted {len(extracted.medicines)} medicines, "
                f"{len(extracted.investigations_ordered)} investigations"
            ),
            metadata={
                "cost_usd": cost,
                "input_tokens": meta.usage.input_tokens if meta.usage else 0,
                "output_tokens": meta.usage.output_tokens if meta.usage else 0,
                "model_id": meta.model_id,
                "latency_ms": meta.latency_ms,
            },
        )

        return extracted
