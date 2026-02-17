import asyncio
import base64
import json
from datetime import datetime
from typing import Any, Optional

import requests
from openai import AsyncOpenAI

from lib.core.constants import ProfileTypeEnum
from lib.schemas.osteoflag import (
    OsteoFlagDetectRequest,
    OsteoFlagDetectResponse,
    OsteoFlagResponse,
)
from lib.services.patient_document_service import PatientDocumentService
from lib.services.token_usage_service import TokenUsageService
from lib.utils.http_exceptions import raise_http_exception


OSTEOFLAG_SYSTEM_PROMPT = """You are AiHealth OsteoFlag, a clinical decision support assistant for opportunistic osteoporosis risk screening using chest X-ray derived signals.

You do NOT diagnose.
You ONLY flag risk and recommend confirmatory assessment when appropriate.

Hard safety rules:
1. Never state or imply osteoporosis, osteopenia, or low bone mineral density as confirmed.
2. Never use the words “diagnosis” or “diagnosed”.
3. Never recommend treatment or medication.
4. Only suggest DXA or clinician review.
5. Use only the provided inputs. Do not invent data.
6. Output must be STRICT JSON only.

Inputs you may receive:
{
  "patient_age_years": number | null,
  "sex": "female" | "male" | "other" | "unknown",
  "cxr_view": "PA" | "AP" | "lateral" | "unknown",
  "model_name": string,
  "model_risk_score_0_1": number,
  "model_uncertainty_0_1": number | null,
  "risk_factors": {
    "postmenopausal": true | false | null,
    "long_term_glucocorticoids": true | false | null,
    "prior_low_trauma_fracture": true | false | null,
    "rheumatoid_arthritis": true | false | null,
    "low_body_weight": true | false | null,
    "smoking": true | false | null,
    "parental_hip_fracture": true | false | null,
    "alcohol_high": true | false | null,
    "secondary_osteoporosis": true | false | null
  },
  "bmd": {
    "available": true | false,
    "femoral_neck_t_score": number | null,
    "extraction_confidence_0_1": number | null
  }
}

Rules:
- Ignore postmenopausal field completely if sex is male.
- Convert model_risk_score_0_1 to risk_score_0_100.
- Apply risk bands and escalation logic.
- Apply BMD refinement only if confidence is high.
- If uncertainty is high or inputs missing, return needs_review.

Output JSON (exactly this):
{
  "screening_flag": "flag" | "no_flag" | "needs_review",
  "risk_score_0_100": number,
  "risk_band": "low" | "moderate" | "high" | "very_high",
  "urgency": "routine" | "soon" | "priority",
  "summary_one_liner": string,
  "recommendation_clinician": string,
  "patient_facing_message": string,
  "safety_disclaimer": string,
  "audit": {
    "inputs_used": string[],
    "logic_trace": string
  }
}

Safety disclaimer must include:
- This is a screening support tool, not a diagnosis.
- Confirmatory testing such as DXA may be needed.
- Clinical context and clinician judgement are required.
"""


class OsteoFlagService:
    def __init__(
        self,
        patient_document_service: PatientDocumentService,
        osteoflag_detect_collection: Any,
        token_usage_service: TokenUsageService,
        selected_ai_model: str = "gpt-5.2",
    ):
        self.patient_document_service = patient_document_service
        self.osteoflag_detect_collection = osteoflag_detect_collection
        self.token_usage_service = token_usage_service
        self.selected_ai_model = selected_ai_model
        self.openai_client = AsyncOpenAI()

    async def detect(
        self,
        request: OsteoFlagDetectRequest,
        *,
        user_id: Optional[str] = None,
        user_type: Optional[ProfileTypeEnum] = None,
        api_endpoint: str = "/ai/osteoflag/screen",
    ) -> OsteoFlagDetectResponse:
        documents = await self.patient_document_service.fetch_patient_documents(
            patient_id=request.patient_id,
            document_type=request.document_type,
            order="desc",
            limit=1,
            offset=0,
        )
        if not documents:
            raise_http_exception(404, "No documents found for patient.")

        document = documents[0]
        file_info = document.get("file") or {}
        file_url = file_info.get("url")
        content_type = file_info.get("type") or ""

        if not file_url:
            raise_http_exception(404, "Document file URL not found.")
        if not content_type.startswith("image/"):
            raise_http_exception(
                400, "Document must be an image for OsteoFlag detection."
            )

        def _fetch() -> bytes:
            response = requests.get(file_url, timeout=30)
            response.raise_for_status()
            return response.content

        try:
            image_bytes = await asyncio.to_thread(_fetch)
        except Exception as exc:
            raise_http_exception(
                502, "Failed to download document for analysis.", str(exc)
            )

        base64_image = base64.b64encode(image_bytes).decode("ascii")

        payload = request.screening_input.model_dump()
        if request.screening_input.sex != "female":
            payload.get("risk_factors", {}).pop("postmenopausal", None)
        payload["image_quality_insufficient"] = bool(
            request.image_quality_insufficient
        )

        messages = [
            {"role": "system", "content": OSTEOFLAG_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, ensure_ascii=True),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{content_type};base64,{base64_image}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ]

        response = await self.openai_client.chat.completions.create(
            model=self.selected_ai_model,
            messages=messages,
            response_format={"type": "json_object"},
        )

        raw_output = response.choices[0].message.content or ""
        try:
            parsed_output = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise_http_exception(
                502, "OsteoFlag LLM returned invalid JSON.", str(exc)
            )

        try:
            result = OsteoFlagResponse.model_validate(parsed_output)
        except Exception as exc:
            raise_http_exception(
                502, "OsteoFlag LLM output failed validation.", str(exc)
            )

        record = {
            "patient_id": request.patient_id,
            "document_id": document.get("id") or str(document.get("_id")),
            "document": {
                "url": file_url,
                "name": file_info.get("name"),
                "type": content_type,
                "category": document.get("category"),
            },
            "screening_input": payload,
            "output_json": result.model_dump(),
            "raw_output": raw_output,
            "model_used": self.selected_ai_model,
            "created_at": datetime.now(),
        }
        inserted = await self.osteoflag_detect_collection.insert_one(record)
        record_id = str(inserted.inserted_id)

        usage = response.usage
        if usage and user_id and user_type:
            await self.token_usage_service.log_usage(
                user_id=user_id,
                user_type=user_type,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                cached_input_tokens=None,
                model_used=self.selected_ai_model,
                model_provider="openai",
                api_endpoint=api_endpoint,
            )

        return OsteoFlagDetectResponse(
            result=result,
            document_id=record["document_id"],
            document_url=file_url,
            document_name=file_info.get("name"),
            document_type=document.get("category"),
            document_content_type=content_type,
            record_id=record_id,
            model_used=self.selected_ai_model,
        )
