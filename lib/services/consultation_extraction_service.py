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
- If a field is not discussed, set it to null (or an empty list for list \
fields, or false for boolean fields).
- Speakers may not be labeled; use clinical context to decide what was said \
by whom.
- Transcripts may be noisy (mishearings, filler words, partial sentences). \
Skip clearly unintelligible fragments.

Provider & visit metadata:
- doctor_name: the doctor's name if introduced or referenced during the \
conversation (e.g., "I'm Dr. Sharma", "Dr. Iyer here"). null if never said.
- prescription_date: the date the prescription is being written, if the \
doctor explicitly states a date during the conversation. null otherwise \
— the server will default to the recording date.

Clinical narrative:
- chief_complaint: the main reason the patient came in, in one short phrase.
- history_of_present_illness: onset, duration, severity, triggers, what makes \
it better/worse, associated symptoms — narrative form.
- past_history_mentioned: any past medical history the patient or doctor \
referenced (chronic conditions, surgeries, allergies). null if nothing \
mentioned.
- examination_findings: anything the doctor states about vitals or physical \
exam during the conversation (e.g., "your BP is 140/90", "your throat looks \
red").
- assessment: the doctor's working diagnosis or impression.
- plan: the doctor's overall plan in narrative form (separate from medicines, \
investigations, lifestyle advice and follow-up, which have their own fields).

Medicines (one object per drug the doctor prescribes during the conversation; \
fill every field that is mentioned, leave the rest null):
- name: generic/active ingredient name (e.g., "Azithromycin").
- brand_name: brand or trade name if the doctor uses one (e.g., "Azithral").
- strength: dose strength as spoken (e.g., "500 mg", "5 ml").
- formulation: form factor (tablet, capsule, syrup, suspension, injection, \
ointment, drops, inhaler, etc.).
- route: administration route (oral, IV, IM, subcutaneous, topical, inhaled, \
nasal, ophthalmic).
- food_timing: timing relative to food (before food, after food, with food, \
empty stomach, anytime).
- purpose: why it's being prescribed in a short phrase, if stated \
(e.g., "for the cough", "for blood pressure").
- instructions: any extra spoken instruction not captured by the structured \
fields (e.g., "shake well before use", "swallow whole, do not crush").
- doses: structured per-slot dosing. Apply these conversions:
    * "1-0-1" → morning quantity 1 + evening quantity 1
    * "1-1-1" → morning + afternoon + evening, each quantity 1
    * "twice a day" / "BD" / "BID" → morning + evening, quantity 1 each
    * "thrice a day" / "TDS" / "TID" → morning + afternoon + evening, \
quantity 1 each
    * "once a day" / "OD" → morning, quantity 1
    * "at bedtime" / "HS" → night, quantity 1
    * "half tablet" → quantity 0.5; "1.5 tablets" → quantity 1.5
    * "SOS" / "PRN" / "as needed" → is_sos=true with empty doses.
- schedule: dosing frequency. null = daily (every day).
    * "daily" / "OD" / unspecified → null
    * "once a week" / "weekly on Monday" → type="weekly", days_of_week=[0]
    * "Mon/Wed/Fri" / "MWF" → type="weekly", days_of_week=[0, 2, 4]
    * "weekdays only" → type="weekly", days_of_week=[0,1,2,3,4]
    * "alternate days" / "every other day" / "QOD" → type="interval", \
interval_days=2, interval_anchor=start_date
    * "every 3 days" → type="interval", interval_days=3, \
interval_anchor=start_date
- start_date: the date the patient starts the medicine. If the doctor implies \
"start today" (or doesn't say otherwise), use prescription_date or the \
recording date — leave null only if the doctor explicitly defers it.
- end_date: compute from start_date + duration when the doctor says e.g. \
"for 5 days", "for 2 weeks", "for 10 days". null if the doctor says \
"continue", "long-term", or doesn't mention duration.
- is_sos: true for PRN / SOS / as-needed; false otherwise.

Investigations & advice:
- investigations_ordered: lab tests, imaging, or other workup the doctor \
orders during the conversation. List each as a short phrase \
(e.g., "Complete blood count", "Chest X-ray PA view").
- lifestyle_advice: non-pharmacological advice the doctor gives (diet, sleep, \
exercise, hydration, smoking/alcohol, etc.). Each as a short phrase.

Follow-up:
- follow_up_required: true if the doctor explicitly asks the patient to come \
back. false otherwise.
- follow_up_date: an actual date if computable from prescription_date plus a \
stated interval (e.g., "come back in 1 week" with prescription_date \
2026-05-21 → 2026-05-28). null if the interval is vague or contingent \
("if it gets worse", "after the labs").
- follow_up_instructions: the natural-language version of the follow-up \
("in 1 week", "after the X-ray results", "if symptoms worsen").

Misc:
- notes: any other doctor instructions or remarks not captured elsewhere \
(referral mentions not yet ordered, admin/billing remarks, general advice). \
null if none.
- red_flags: warning signs the doctor tells the patient to watch for. Each \
as a short phrase (e.g., "worsening shortness of breath", "fever above 39 C").
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
