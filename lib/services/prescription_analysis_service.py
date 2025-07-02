from datetime import datetime
from typing import Any, Union

from decouple import config
from langchain.schema import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from lib.core.constants import AI_RESPONSE_SAFETY_DISCLAIMER, ProfileTypeEnum
from lib.core.postgres_store import PostgresStore
from lib.core.types import (
    AIModelProviderLiteral,
    GeminiAIModelLiteral,
    OpenAIModelLiteral,
)

from lib.schemas.patient_prescription_analysis import (
    PrescriptionAnalysisResponse,
)
from lib.services.token_usage_service import TokenUsageService
from lib.utils.retry_utils import retry_request


class PrescriptionAnalysisService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        token_usage_service: TokenUsageService,
        timezone="Asia/Kolkata",
        ai_model_provider: AIModelProviderLiteral = "openai",
        selected_ai_model: Union[
            OpenAIModelLiteral, GeminiAIModelLiteral
        ] = "gpt-4o",
    ):
        self.postgres_store = postgres_store
        self.token_usage_service = token_usage_service
        self.timezone = timezone
        self.selected_ai_model = selected_ai_model
        self.ai_model_provider = ai_model_provider

        if ai_model_provider == "openai":
            self.chat_model = ChatOpenAI(
                model=selected_ai_model,
                temperature=0.4,
                api_key=SecretStr(str(config("OPENAI_API_KEY"))),
            )
        else:
            self.chat_model = ChatGoogleGenerativeAI(
                model=selected_ai_model,
                temperature=0.4,
                api_key=SecretStr(str(config("GOOGLE_API_KEY"))),
            )

        self.structured_model = self.chat_model.with_structured_output(
            PrescriptionAnalysisResponse, include_raw=True
        )

    async def analyze_prescription(
        self,
        image_url: str,
        user_id: str,
        user_type: ProfileTypeEnum,
    ) -> PrescriptionAnalysisResponse:
        system_prompt = [
            SystemMessage(
                content=(
                    "You are a highly skilled medical assistant AI. Your job is to extract structured prescription data "
                    "AND educate the patient. From the image, you must:\n"
                    "1. Extract doctor name, patient name, date.\n"
                    "2. Extract a list of medicines with name, dosage, frequency, duration.\n"
                    "3. For each medicine, explain in simple language:\n"
                    "   - What it does\n"
                    "   - How and when to take it\n"
                    "   - Any common side effects or precautions\n"
                    "   - Why it’s important to follow the instructions\n"
                    "4. Provide a final summary that encourages adherence.\n\n"
                    f"Always follow medical safety rules. {AI_RESPONSE_SAFETY_DISCLAIMER}"
                )
            ),
        ]

        human_messages = [
            HumanMessage(
                content=[
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                ]
            )
        ]

        messages = system_prompt + human_messages

        ai_response: Any = retry_request(
            self.structured_model.invoke, input=messages
        )

        parsed_response: PrescriptionAnalysisResponse = ai_response.get(
            "parsed", {}
        )
        usage_metadata = ai_response["raw"].usage_metadata

        if usage_metadata:
            await self.token_usage_service.log_usage(
                user_id=user_id,
                user_type=user_type,
                input_tokens=usage_metadata["input_tokens"],
                output_tokens=usage_metadata["output_tokens"],
                cached_input_tokens=usage_metadata.get("cached_input_tokens"),
                model_used=self.selected_ai_model,
                model_provider=self.ai_model_provider,
                api_endpoint="/patient/prescription/analyze",
            )  # type: ignore

        return parsed_response
