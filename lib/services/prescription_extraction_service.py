"""Extracts structured prescription data from images using ModelGateway.

Single responsibility: image → structured JSON. No summaries, no intelligence.
"""

from __future__ import annotations

import logging

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
    ) -> ExtractedPrescription:
        """Extract structured prescription data from one or more images."""
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
            model_id="gpt-4o",
        )

        logger.info(
            "Prescription extracted: %d medicines, %dms, $%.4f",
            len(extracted.medicines),
            meta.latency_ms,
            meta.usage.cost if meta.usage else 0,
        )

        return extracted
