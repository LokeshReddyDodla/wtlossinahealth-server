"""Generic vision extraction into the canonical Body Composition schema."""

from __future__ import annotations

import base64
import io
from typing import Any
from uuid import uuid4

from decouple import config

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.schemas.body_composition import BodyCompositionExtraction

EXTRACTION_MODEL_ID = config(
    "BODY_COMPOSITION_EXTRACTION_MODEL_ID", default="gpt-5.2"
)
MAX_PDF_PAGES = 3

SYSTEM_PROMPT = """You extract structured Body Composition measurements from
clinical analyzer reports. The report may come from any manufacturer and may
use BIA, DXA, air-displacement plethysmography, or another method. Never assume
the manufacturer, device, or method; use UNKNOWN/null when it is not printed or
reliably identifiable.

Capture only values visible in the current report. Use these canonical metric
keys when applicable: weight, total_body_water, intracellular_water,
extracellular_water, protein, minerals, bone_mineral_content, soft_lean_mass,
fat_free_mass, skeletal_muscle_mass, body_fat_mass, percent_body_fat, bmi,
waist_hip_ratio, waist_circumference, visceral_fat_level, visceral_fat_area,
ecw_tbw_ratio, phase_angle, smi, basal_metabolic_rate, body_cell_mass,
obesity_degree, target_weight, weight_control, fat_control, muscle_control, and
device_score. Preserve the printed label for vendor-specific metrics. Include
the printed unit and reference range. Set confidence separately for every value.

Capture segmental lean/fat values for right arm, left arm, trunk, right leg,
and left leg. Capture impedance only when exact numeric values are printed;
never estimate values from a graph. Do not copy historical values printed in a
history panel into the current record. Do not provide medical interpretation."""


class BodyCompositionExtractionService:
    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    async def extract(
        self,
        *,
        file_bytes: bytes,
        content_type: str,
        patient_id: str,
    ) -> BodyCompositionExtraction:
        images = self._image_urls(file_bytes, content_type)
        trace_id = str(uuid4())
        self.gateway.set_langfuse_context(
            session_id=f"body-composition:{patient_id}", user_id=patient_id
        )
        self.gateway.langfuse_trace_input(
            trace_id=trace_id,
            name="body-composition-preview",
            input_text="Extract a body-composition report",
            metadata={"content_type": content_type, "page_count": len(images)},
        )

        content: list[dict[str, Any]] = [
            {"type": "text", "text": "Extract the current report."}
        ]
        content.extend(
            {"type": "image_url", "image_url": {"url": image}}
            for image in images
        )
        extraction, meta = await self.gateway.extract(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_model=BodyCompositionExtraction,
            task=ModelTask.STRUCTURED_ANALYSIS,
            model_id=EXTRACTION_MODEL_ID,
            trace_id=trace_id,
        )
        usage = meta.usage
        self.gateway.langfuse_trace_output(
            trace_id=trace_id,
            output_text="Body-composition extraction completed",
            metadata={
                "model_id": meta.model_id,
                "latency_ms": meta.latency_ms,
                "input_tokens": usage.input_tokens if usage else 0,
                "output_tokens": usage.output_tokens if usage else 0,
                "cost_usd": usage.cost.total_cost if usage else 0,
                "measurement_count": len(extraction.measurements),
                "confidence": extraction.extraction_confidence,
            },
        )
        return extraction

    @classmethod
    def _image_urls(cls, file_bytes: bytes, content_type: str) -> list[str]:
        if content_type == "application/pdf":
            from pdf2image import convert_from_bytes

            pages = convert_from_bytes(file_bytes, dpi=200)[:MAX_PDF_PAGES]
            urls: list[str] = []
            for page in pages:
                buffer = io.BytesIO()
                page.save(buffer, format="PNG")
                encoded = base64.b64encode(buffer.getvalue()).decode()
                urls.append(f"data:image/png;base64,{encoded}")
            if not urls:
                raise ValueError("PDF contains no readable pages")
            return urls

        if content_type not in {"image/jpeg", "image/jpg", "image/png"}:
            raise ValueError("Unsupported body-composition report type")
        encoded = base64.b64encode(file_bytes).decode()
        mime = "image/png" if content_type == "image/png" else "image/jpeg"
        return [f"data:{mime};base64,{encoded}"]
