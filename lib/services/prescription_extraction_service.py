"""Extracts structured prescription data from images using ModelGateway.

Single responsibility: image → structured JSON. No summaries, no intelligence.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.schemas.medication import ExtractedPrescription

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a prescription data extractor. Given one or more prescription images, \
extract the structured data into the provided JSON schema.

Rules:
- Extract exactly what is written on the prescription.
- For each medicine, determine the dosing schedule and convert it to structured \
dose slots: morning, afternoon, evening, night.
  - "1-0-1" means 1 in the morning, 0 in the afternoon, 1 in the evening.
  - "1-1-1" means morning, afternoon, and evening.
  - "Twice a day" means morning and evening.
  - "Once a day" means morning.
  - "At bedtime" / "HS" means night.
  - "SOS" / "PRN" / "As needed" means is_sos=true with no doses.
  - Quantity can be fractional: "half tablet" = 0.5, "1.5 tablets" = 1.5.
- For scheduling frequency:
  - "Daily" / "OD" / no explicit frequency → schedule is null (defaults to every day).
  - "Once a week" / "Weekly on Monday" → schedule.type="weekly", schedule.days_of_week=[0] (Mon=0..Sun=6).
  - "Twice a week" → schedule.type="weekly", pick two spread-out days like [0, 3] (Mon, Thu).
  - "Mon/Wed/Fri" or "MWF" → schedule.type="weekly", schedule.days_of_week=[0, 2, 4].
  - "Weekdays only" → schedule.type="weekly", schedule.days_of_week=[0,1,2,3,4].
  - "Alternate days" / "Every other day" / "QOD" → schedule.type="interval", schedule.interval_days=2, schedule.interval_anchor=start_date.
  - "Every 3 days" / "Every 72 hours" → schedule.type="interval", schedule.interval_days=3, schedule.interval_anchor=start_date.
  - If frequency is unclear, set schedule to null (daily is the safe default).
- Calculate end_date from the prescription date + duration if both are available.
- Calculate follow_up_date from the prescription date + follow-up interval if \
mentioned.
- If a field is not present or not legible, set it to null.
- Do NOT invent information that is not on the prescription.
"""


class PrescriptionExtractionService:
    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    async def extract(
        self,
        image_urls: list[str],
        *,
        patient_id: str | None = None,
    ) -> ExtractedPrescription:
        """Extract structured prescription data from one or more images."""
        trace_id = str(uuid4())
        if patient_id:
            self.gateway.set_langfuse_context(
                session_id=f"prescription:{patient_id}", user_id=patient_id,
            )
        self.gateway.langfuse_trace_input(
            trace_id=trace_id,
            name="prescription-extraction",
            input_text=f"Extract prescription from {len(image_urls)} image(s)",
        )

        image_content = [
            {"type": "image_url", "image_url": {"url": url}}
            for url in image_urls
        ]

        messages: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract the prescription data from these images."},
                    *image_content,
                ],
            },
        ]

        extracted, meta = await self.gateway.extract(
            messages=messages,
            response_model=ExtractedPrescription,
            task=ModelTask.STRUCTURED_ANALYSIS,
            model_id="gpt-5.2",
            trace_id=trace_id,
        )

        cost = meta.usage.cost.total_cost if meta.usage else 0
        logger.info(
            "Prescription extracted: %d medicines, %dms, $%.4f",
            len(extracted.medicines),
            meta.latency_ms,
            cost,
        )

        self.gateway.langfuse_trace_output(
            trace_id=trace_id,
            output_text=f"Extracted {len(extracted.medicines)} medicines",
            metadata={
                "cost_usd": cost,
                "input_tokens": meta.usage.input_tokens if meta.usage else 0,
                "output_tokens": meta.usage.output_tokens if meta.usage else 0,
                "model_id": meta.model_id,
                "latency_ms": meta.latency_ms,
            },
        )

        return extracted