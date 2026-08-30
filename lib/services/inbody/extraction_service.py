"""Vision-LLM extraction of InBody result sheets into typed structures.

One structured call via ``ModelGateway.extract`` — no free-text parsing.
PDFs are rasterised to images first because vision endpoints only accept
images. Low-confidence extractions are routed to ``needs_review`` rather
than silently stored.
"""

from __future__ import annotations

import base64
import io
from typing import Any, Dict, List

from loguru import logger

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.schemas.inbody import InbodyExtraction

# Below this self-assessed confidence the report is stored but flagged for a
# human look instead of feeding trends/insights.
NEEDS_REVIEW_THRESHOLD = 0.7

MAX_PDF_PAGES = 3

EXTRACTION_SYSTEM_PROMPT = (
    "You are a medical data extraction system reading an InBody body-"
    "composition result sheet. Extract every legible measurement exactly as "
    "printed — never estimate, infer or fill in values that are not visible. "
    "Use canonical snake_case measurement names. Report values in the units "
    "printed on the sheet. Include normal ranges when printed. For segmental "
    "lean/fat analysis capture each body segment. Also read the evaluation "
    "sections when the sheet prints them: Nutritional Evaluation (rate "
    "protein, minerals, body fat, body water as under/normal/over), Obesity "
    "Evaluation (rate BMI and percent body fat), and Balance of Body (rate "
    "upper, lower and upper-lower as balanced/slightly_imbalanced/"
    "imbalanced). For impedance, do not transcribe the full per-segment ohm "
    "grid — give impedance_note as a one to two sentence read of whether the "
    "readings look consistent/typical or show an anomaly. Leave any section "
    "null if the sheet does not print it. Set extraction_confidence honestly: "
    "reduce it when the image is blurry, cropped, or values are ambiguous, "
    "and list the problems in notes."
)


class InbodyExtractionService:
    def __init__(self, model_gateway: ModelGateway) -> None:
        self.model_gateway = model_gateway

    async def extract(
        self,
        *,
        file_bytes: bytes,
        content_type: str,
        report_id: str,
    ) -> InbodyExtraction:
        """Run one typed vision extraction over the uploaded file.

        Raises on LLM failure — the caller owns status transitions and
        retry policy.
        """

        image_urls = self._to_image_data_urls(file_bytes, content_type)

        logger.info(
            "inbody: extracting report={} content_type={} images={}",
            report_id,
            content_type,
            len(image_urls),
        )

        user_content: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Extract all body-composition data from this InBody "
                    "result sheet."
                ),
            }
        ]
        for url in image_urls:
            user_content.append(
                {"type": "image_url", "image_url": {"url": url}}
            )

        extraction, meta = await self.model_gateway.extract(
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_model=InbodyExtraction,
            task=ModelTask.VISION,
        )

        logger.info(
            "inbody: extraction done report={} model={} confidence={} "
            "measurements={} segments={}",
            report_id,
            meta.model_id,
            extraction.extraction_confidence,
            len(extraction.measurements),
            len(extraction.segmental_lean) + len(extraction.segmental_fat),
        )
        return extraction

    @staticmethod
    def needs_review(extraction: InbodyExtraction) -> bool:
        return (
            extraction.extraction_confidence < NEEDS_REVIEW_THRESHOLD
            or not extraction.measurements
        )

    # ------------------------------------------------------------------
    # File handling
    # ------------------------------------------------------------------

    def _to_image_data_urls(
        self, file_bytes: bytes, content_type: str
    ) -> List[str]:
        if content_type == "application/pdf":
            return self._pdf_to_data_urls(file_bytes)
        if content_type in ("image/jpeg", "image/jpg", "image/png"):
            encoded = base64.b64encode(file_bytes).decode("utf-8")
            mime = "image/png" if content_type == "image/png" else "image/jpeg"
            return [f"data:{mime};base64,{encoded}"]
        raise ValueError(f"Unsupported content type: {content_type}")

    @staticmethod
    def _pdf_to_data_urls(file_bytes: bytes) -> List[str]:
        from pdf2image import convert_from_bytes

        pages = convert_from_bytes(file_bytes, dpi=200)[:MAX_PDF_PAGES]
        if not pages:
            raise ValueError("PDF produced no pages")

        urls: List[str] = []
        for page in pages:
            buffer = io.BytesIO()
            page.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
            urls.append(f"data:image/png;base64,{encoded}")
        return urls
