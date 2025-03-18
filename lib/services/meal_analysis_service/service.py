from typing import Any, Dict, Optional

from decouple import config
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from schemas import MealAnalysisResponse, MealAnalysisResult, TokenUsage


class MealAnalysisService:
    def __init__(self):
        self.chat_model = ChatOpenAI(
            model="gpt-4o",
            temperature=0.2,
            api_key=SecretStr(str(config("OPENAI_API_KEY"))),
        )
        self.structured_model = self.chat_model.with_structured_output(
            MealAnalysisResponse, include_raw=True
        )

    async def analyze_meal(
        self,
        context: Dict[str, Any],  # Generic context for analysis
        meal_time: str,
        meal_type: str,
        image_url: Optional[str] = None,
        meal_description: Optional[str] = None,
        update_fields: Optional[Dict[str, Any]] = None,
    ) -> MealAnalysisResult:
        # System message for the AI
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
                    "especially during breakfast, lunch, or dinner."
                )
            ),
            SystemMessage(content=f"Context:\n```json\n{context}\n```"),
        ]

        # Human messages (user input)
        human_messages = [
            HumanMessage(content=f"I had {meal_type} at {meal_time}.")
        ]

        # Add image URL if provided
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

        # Add meal description if provided
        if meal_description:
            human_messages.append(
                HumanMessage(content=f"Description: {meal_description}")
            )

        # Add update fields if provided
        if update_fields:
            human_messages.append(
                HumanMessage(content=f"Updated Details: {update_fields}")
            )

        # Combine system and human messages
        messages = system_message + human_messages

        # Call the AI model
        ai_response = self.structured_model.invoke(input=messages)

        token_usage: TokenUsage = ai_response["raw"].usage_metadata
        parsed_response: MealAnalysisResponse = ai_response.get("parsed", {})

        return MealAnalysisResult(
            meal_information=parsed_response,
            token_usage=token_usage,
        )
