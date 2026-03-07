from typing import Any, Union

from decouple import config
from langchain_core.messages import HumanMessage, SystemMessage
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
from lib.schemas.patient_meal import MealAnalysisResponse
from lib.services.token_usage_service import TokenUsageService
from lib.utils.retry_utils import retry_request


class MealAnalysisService:
    """Service for AI-powered meal analysis."""

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
        self.selected_ai_model: Union[
            OpenAIModelLiteral, GeminiAIModelLiteral
        ] = selected_ai_model
        self.ai_model_provider: AIModelProviderLiteral = ai_model_provider

        if ai_model_provider == "openai":
            self.chat_model = ChatOpenAI(
                model=self.selected_ai_model,
                temperature=0.5,
                api_key=SecretStr(str(config("OPENAI_API_KEY"))),
            )
        else:
            self.chat_model = ChatGoogleGenerativeAI(
                model=self.selected_ai_model,
                temperature=0.5,
                api_key=SecretStr(str(config("GOOGLE_API_KEY"))),
            )
        self.structured_model = self.chat_model.with_structured_output(
            MealAnalysisResponse, include_raw=True
        )

    async def analyze_meal(
        self,
        patient_id,
        patient_profile_json,
        meal_time,
        image_url,
        meal_type,
        meal_description=None,
        update_fields=None,
    ):
        system_message = [
            SystemMessage(
                content=(
                    "You are an AI strictly focused on meal analysis with deep knowledge "
                    "of Indian cuisine and nutritional science. Respond with precise analysis "
                    "based on the given schema. Avoid unrelated topics and ensure your response "
                    "follows these considerations:\n\n"
                    "1. Identify all visible food items and provide their coordinates.\n"
                    "2. Use realistic serving sizes (grams, cups, pieces). If unclear, predict typical serving sizes "
                    "based on meal type (e.g., breakfast, lunch) and time of day.\n"
                    "3. Avoid suggesting high-GI foods with main meals unless appropriate.\n"
                    "4. Assign a score out of 10 and glycemic index tags ('high', 'medium', 'low').\n"
                    "5. Suggest culturally relevant and healthier alternatives without compromising taste.\n"
                    "6. Offer personalized feedback to align meals with macronutrient goals based on user factors.\n"
                    "7. Avoid recommending foods that may cause blood sugar spikes, "
                    "especially during breakfast, lunch, or dinner.\n"
                    "8. Include carbohydrate distribution in macro values using `simple_carbs` "
                    "and `complex_carbs` for each item and total; keep `carbohydrates` as total carbs. "
                    "Prefer providing both fields whenever possible, and keep "
                    "`simple_carbs + complex_carbs ~= carbohydrates`.\n\n"
                    f"Safety Rules: {AI_RESPONSE_SAFETY_DISCLAIMER}"
                )
            ),
            SystemMessage(
                content=f"Patient Profile:\n```json\n{patient_profile_json}\n```"
            ),
        ]

        human_messages = [
            HumanMessage(content=f"I had {meal_type} at {meal_time}.")
        ]

        if image_url:
            human_messages.append(
                HumanMessage(
                    content=[
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url},
                        },
                    ]
                )
            )

        if meal_description:
            human_messages.append(
                HumanMessage(content=f"Description: {meal_description}")
            )

        if update_fields:
            human_messages.append(
                HumanMessage(
                    content=f"Updated Serving Details: {update_fields}"
                )
            )

        messages = system_message + human_messages

        ai_response: Any = retry_request(
            self.structured_model.invoke,
            input=messages,
        )

        parsed_response: MealAnalysisResponse = ai_response.get("parsed", {})
        usage_metadata = ai_response["raw"].usage_metadata

        if usage_metadata:
            await self.token_usage_service.log_usage(
                user_id=patient_id,
                user_type=ProfileTypeEnum.PATIENT,
                input_tokens=usage_metadata["input_tokens"],
                output_tokens=usage_metadata["output_tokens"],
                cached_input_tokens=usage_metadata.get("cached_input_tokens"),
                model_used=self.selected_ai_model,
                model_provider=self.ai_model_provider,
                api_endpoint="/patient/meals/analyze",
            )

        return parsed_response

    async def reanalyze_meal(
        self,
        patient_id: str,
        meal_json: dict,
        update_fields: dict,
    ):
        meal_json_for_reanalysis = self._sanitize_meal_for_reanalysis(
            meal_json
        )
        system_message = [
            SystemMessage(
                content=(
                    "You are an AI focused on reanalyzing meal data. "
                    "Use the provided meal details and updated serving fields "
                    "to adjust the nutritional analysis and feedback.\n\n"
                    "If there are conflicts between original details and updated details, "
                    "ALWAYS prioritize updated details (especially the description). "
                    "Include carbohydrate distribution in macro values using `simple_carbs` "
                    "and `complex_carbs`, while keeping `carbohydrates` as total carbs. "
                    "Prefer providing both fields whenever possible and keep "
                    "`simple_carbs + complex_carbs ~= carbohydrates`. "
                    f"Safety Rules: {AI_RESPONSE_SAFETY_DISCLAIMER}"
                )
            ),
            SystemMessage(
                content=f"Original Meal Details:\n```json\n{meal_json_for_reanalysis}\n```"
            ),
        ]

        human_messages = [
            HumanMessage(
                content="Reanalyze the meal based on the updated details."
            )
        ]

        if update_fields:
            human_messages.append(
                HumanMessage(
                    content=f"Updated Meal Details:\n```json\n{update_fields}\n```"
                )
            )

        messages = system_message + human_messages

        ai_response: Any = retry_request(
            self.structured_model.invoke,
            input=messages,
        )

        parsed_response: MealAnalysisResponse = ai_response.get("parsed", {})
        usage_metadata = ai_response["raw"].usage_metadata

        if usage_metadata:
            await self.token_usage_service.log_usage(
                user_id=patient_id,
                user_type=ProfileTypeEnum.PATIENT,
                input_tokens=usage_metadata["input_tokens"],
                output_tokens=usage_metadata["output_tokens"],
                cached_input_tokens=usage_metadata.get("cached_input_tokens"),
                model_used=self.selected_ai_model,
                model_provider=self.ai_model_provider,
                api_endpoint="/patient/meals/analyze",
            )

        return parsed_response

    @staticmethod
    def _sanitize_meal_for_reanalysis(meal_json: dict) -> dict:
        """Remove old nutrition payloads so reanalysis is not anchored to prior bad values."""
        if not isinstance(meal_json, dict):
            return meal_json

        sanitized = dict(meal_json)
        sanitized.pop("total_macro_nutritional_value", None)
        sanitized.pop("total_micro_nutritional_value", None)

        sanitized_items = []
        for item in sanitized.get("items", []) or []:
            if not isinstance(item, dict):
                sanitized_items.append(item)
                continue
            sanitized_item = dict(item)
            sanitized_item.pop("macro_nutritional_values", None)
            sanitized_item.pop("micro_nutritional_values", None)
            sanitized_items.append(sanitized_item)

        sanitized["items"] = sanitized_items
        return sanitized
