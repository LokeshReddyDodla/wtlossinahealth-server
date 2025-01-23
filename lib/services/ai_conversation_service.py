from typing import Any, Dict, List, Optional
from uuid import UUID

from decouple import config
from fastapi import status
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr, ValidationError

from lib.core.types import (AiConversationMessageTypeLiteral,
                            AiConversationRoleLiteral,
                            AiConversationTypeLiteral, OpenAIModelLiteral)
from lib.schemas.ai_conversation_schemas import \
    AiConversationMessage as AiConversationMessageSchema
from lib.schemas.ai_conversation_schemas import AiResponseSuggestions
from lib.schemas.patient import CorePatientProfile
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.patient_token_usage_logger import PatientTokenUsageLogger


class AiConversationService:
    def __init__(
        self,
        conversation_type: AiConversationTypeLiteral = "other",
        model: OpenAIModelLiteral = "gpt-4o",
    ):
        from lib.core.container import container

        self.patient_profile_service: Any = container.resolve(
            PatientProfileService
        )
        self.ai_messages_collection: Any = container.resolve(
            "ai_conversation_messages_collection"
        )
        self.current_model: OpenAIModelLiteral = model

        # Initialize ChatOpenAI with the specified model
        self.chat_model = ChatOpenAI(
            model=self.current_model,
            temperature=0.5,
            api_key=SecretStr(str(config("OPENAI_API_KEY"))),
        )
        self.system_message = self._get_initial_system_message(
            conversation_type
        )

    def _get_initial_system_message(
        self, conversation_type: AiConversationTypeLiteral
    ) -> SystemMessage:
        """Returns the initial system message based on conversation type."""

        if conversation_type == "meal":
            return SystemMessage(
                content="""
                You are an AI strictly focused on meal analysis for diabetic and obese patients. 
                Be friendly, respectful, and polite. Use patient-specific information from the context message to greet or personalize responses.
                Respond only with information related to the current meal, its nutrition, and dietary insights in markdown format. Avoid mentioning any unrelated meals or mixing multiple meals from different times of the day.

                **Guidelines:**
                1. Recommend only low-glycemic index (GI) foods to help control blood sugar.
                2. Prioritize high-fiber, low-GI alternatives to high-GI foods.
                3. Suggest regional, culturally relevant, and healthy alternatives.
                4. Avoid high-sugar, high-fat, and highly processed foods.
                5. Always respond concisely in markdown, highlighting key nutritional insights and healthy alternatives.

                **Important:** 
                - If the user refers to a different meal, politely ask them to upload details or images of that meal to start a new conversation.
                - Stay focused only on the meal currently being discussed without assuming or mixing it with other meals from the same day.
                """
            )
        elif conversation_type == "smbg":
            return SystemMessage(
                content=(
                    "You are an AI assistant specialized in analyzing Self-Monitoring of Blood Glucose (SMBG) data for diabetic and health management. "
                    "Be friendly, respectful, and concise. Provide insights on glucose levels, patterns, and health recommendations in markdown format. "
                    "Remind users to consult their care provider for a professional interpretation and further guidance. Ensure your response is clear, context-specific, and avoids unrelated information."
                )
            )
        elif conversation_type == "sleep":
            return SystemMessage(
                content=(
                    "You are an AI assistant specialized in sleep analysis and feedback for diabetic and obese patients. "
                    "Provide insights into sleep quality, patterns, and recommendations for improvement. "
                    "Focus on sleep duration, timing, and quality metrics such as efficiency and restorative sleep. "
                    "Use markdown to highlight key insights and actionable feedback in a friendly tone."
                    "\n\n**Guidelines:**\n"
                    "1. Provide personalized feedback based on sleep duration, quality, and timing.\n"
                    "2. Highlight potential correlations between sleep and other health data like glucose, fitness, or meals.\n"
                    "3. Suggest practical tips for improving sleep habits, such as maintaining a consistent bedtime, creating a relaxing pre-sleep routine, or adjusting meal timing.\n"
                    "4. Be culturally sensitive and avoid generic advice that may not be relevant to the user's lifestyle.\n"
                    "5. Clearly explain metrics like sleep efficiency and restorative sleep percentage in an easy-to-understand way."
                    "\n\n**Example Feedback:**\n"
                    "- '**Great job!** Your sleep efficiency is **90%**, indicating very effective sleep. Keep up the consistent bedtime routine!'\n"
                    "- 'Your **deep sleep** duration is slightly low. Consider avoiding screens and caffeine before bedtime for better restorative sleep.'\n"
                    "- 'Your bedtime varies by several hours. Try to maintain a consistent schedule for better sleep quality.'"
                )
            )
        elif conversation_type == "prescription":
            return SystemMessage(
                content=(
                    "You are an AI focused on prescription analysis. Use a friendly and respectful tone. "
                    "Respond only with information related to prescriptions, medical details, and relevant insights in markdown format."
                    "Avoid any response that includes your origin, development, or unrelated topics."
                )
            )
        elif conversation_type == "report":
            return SystemMessage(
                content=(
                    "You are an AI specialized in health report analysis. Use a friendly and polite tone. "
                    "Provide insights relevant to the patient's health reports and their content in markdown format."
                    "Avoid any response that includes your origin, development, or unrelated topics."
                )
            )
        elif conversation_type == "health-tip":
            return SystemMessage(
                content=(
                    "You are an AI specialized in health tips for diabetic and obese patients, providing friendly, concise, and actionable advice. "
                    "Generate a brief health tip in 1-2 sentences that is directly relevant to the patient's health goals, and include a friendly, conversational tone. "
                    "Use **bold** formatting to highlight important words or phrases (such as food names, actions, or reminders), making the tip visually engaging. "
                    "Personalize tips by starting with phrases like 'Hi [name],', 'Did you know?', or 'Make sure to...', using the patient's name if available. "
                    "Focus on dietary advice, light activity suggestions, hydration reminders, and general wellness tips that are easy to follow and suitable for display on a mobile home screen."
                    "**Guidelines:**\n"
                    "1. Recommend only low-glycemic index (GI) and high-fiber foods to help manage blood sugar, using **bold** to emphasize specific food items.\n"
                    "2. Encourage light activities such as **walking**, **stretching**, or **breathing exercises**, tailored to the patient's profile.\n"
                    "3. Include hydration reminders and stress-relief tips, keeping suggestions friendly and actionable.\n"
                    "4. Make culturally relevant suggestions and avoid any reference to external apps or tools.\n"
                    "**Examples:**\n"
                    "- '**Hi [name]**, consider a short **walk after lunch** today to help manage blood sugar levels!'\n"
                    "- '**Did you know?** Staying **hydrated** can improve energy levels. Aim to drink water throughout the day.'\n"
                    "- '**Make sure** to include a **high-fiber vegetable** in your next meal for better blood sugar control.'"
                )
            )
        return SystemMessage(
            content=(
                "You are a highly knowledgeable health assistant specializing in analyzing and managing diabetes, obesity, and overall well-being. "
                "Respond in a friendly and respectful tone, offering personalized advice and insights tailored to the patient's profile. "
                "Use your expertise to correlate multiple health data points such as CGM (Continuous Glucose Monitoring), sleep patterns, meals, fitness activities, and other relevant health metrics. "
                "Generate actionable insights that highlight patterns, identify potential issues, and provide recommendations for improvement. "
                "Focus on aligning your responses with the patient's health goals by offering practical, culturally relevant suggestions and highlighting areas that need attention. "
                "Always format your responses in markdown for clarity and engagement, and ensure your advice is easy to understand and actionable. "
                "Avoid mentioning anything unrelated to the specific task or context of the conversation, including your origin or development. "
                "Keep responses concise, evidence-based, and focused on improving the patient's overall health and quality of life."
            )
        )

    async def add_message_to_conversation(
        self,
        patient_id: str,
        conversation_id: str,
        conversation_type: AiConversationTypeLiteral,
        role: AiConversationRoleLiteral,
        content: str,
        message_type: AiConversationMessageTypeLiteral = "text",
        exclude_from_frontend: bool = False,
        reply_suggestions: Optional[List[str]] = None,
    ):
        message_data = AiConversationMessageSchema(
            patient_id=patient_id,
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            role=role,
            content=content,
            message_type=message_type,
            exclude_from_frontend=exclude_from_frontend,
            reply_suggestions=reply_suggestions,
        ).model_dump()

        result = await self.ai_messages_collection.insert_one(message_data)
        message_data["_id"] = str(result.inserted_id)
        return message_data

    async def add_multiple_messages_to_conversation(
        self,
        messages: List[AiConversationMessageSchema],
    ):
        """Batch inserts multiple messages into a conversation."""
        message_data = [message.model_dump() for message in messages]
        await self.ai_messages_collection.insert_many(message_data)

    async def fetch_conversation_messages(
        self,
        conversation_id: str,
        return_raw: bool = False,
        for_frontend: bool = False,
    ) -> List[Any]:
        """Fetch all messages for a given conversation."""
        filters: Any = {"conversation_id": conversation_id}

        if for_frontend:
            filters["exclude_from_frontend"] = False

        pipeline = [
            {"$match": filters},
            {"$sort": {"timestamp": 1}},
            {"$addFields": {"_id": {"$toString": "$_id"}}},
        ]

        messages_cursor = self.ai_messages_collection.aggregate(pipeline)

        if return_raw:
            return await messages_cursor.to_list(length=None)

        messages = []
        async for message in messages_cursor:
            if message["role"] == "system":
                messages.append(SystemMessage(content=message["content"]))
            elif message["role"] == "human":
                messages.append(HumanMessage(content=message["content"]))
            elif message["role"] == "ai":
                messages.append(AIMessage(content=message["content"]))

        return messages

    async def fetch_all_user_conversation_messages(
        self,
        patient_id: str,
        return_raw: bool = False,
        for_frontend: bool = False,
    ) -> List[Any]:
        """Fetch all messages for a given conversation."""
        filters: Any = {"patient_id": patient_id}

        if for_frontend:
            filters["exclude_from_frontend"] = False

        pipeline = [
            {"$match": filters},
            {"$sort": {"timestamp": 1}},
            {"$addFields": {"_id": {"$toString": "$_id"}}},
        ]

        messages_cursor = self.ai_messages_collection.aggregate(pipeline)

        if return_raw:
            return await messages_cursor.to_list(length=None)

        messages = []
        async for message in messages_cursor:
            if message["role"] == "system":
                messages.append(SystemMessage(content=message["content"]))
            elif message["role"] == "human":
                messages.append(HumanMessage(content=message["content"]))
            elif message["role"] == "ai":
                messages.append(AIMessage(content=message["content"]))

        return messages

    async def create_patient_context_message(
        self, patient_id: str
    ) -> SystemMessage:
        """Generate a system message containing the patient's profile."""
        patient = await self.patient_profile_service.fetch_patient_profile(
            patient_id=patient_id, detailed=True, include_health_data=True
        )
        patient_profile_json = CorePatientProfile.from_orm(
            patient
        ).model_dump()
        return SystemMessage(
            content=f"Patient Profile:\n```json\n{patient_profile_json}\n```"
        )

    async def generate_response(
        self,
        patient_id: str,
        conversation_id: str,
        human_input: str,
        conversation_type: AiConversationTypeLiteral,
        include_reply_suggestions: bool = True,
    ) -> Dict:
        await self.add_message_to_conversation(
            patient_id,
            conversation_id,
            conversation_type,
            "human",
            human_input,
        )

        # Fetch all messages to provide context, inserting the system message at the start
        if conversation_id == f"{patient_id}-custom":
            messages = await self.fetch_all_user_conversation_messages(
                patient_id
            )
        else:
            messages = await self.fetch_conversation_messages(conversation_id)
        messages.insert(0, self.system_message)

        # Fetch the patient profile and generate context message
        patient_context_message = await self.create_patient_context_message(
            patient_id
        )
        messages.insert(1, patient_context_message)

        # Generate a response using the chat model
        ai_response: Any = self.chat_model.invoke(messages)

        reply_suggestions = None
        if include_reply_suggestions:
            reply_suggestions = await self._generate_message_suggestions(
                ai_response.content
            )

        ai_message_data = await self.add_message_to_conversation(
            patient_id,
            conversation_id,
            conversation_type,
            "ai",
            ai_response.content,
            message_type="markdown",
            reply_suggestions=reply_suggestions,
        )

        # Log token usage
        tokens_used = ai_response.response_metadata.get("token_usage", {}).get(
            "total_tokens", 0
        )
        if tokens_used:
            await PatientTokenUsageLogger.log_usage(
                patient_id=UUID(patient_id),
                tokens_used=tokens_used,
                model_used=self.current_model,
                api_type="openai",
                api_endpoint="/ai-conversation/respond",
            )

        return ai_message_data

    async def generate_temporary_response(
        self,
        patient_id: str,
        human_input: str,
    ) -> str:
        """
        Generate a response without saving any messages to the database.
        """

        # Fetch all messages for the user to provide context
        messages = await self.fetch_all_user_conversation_messages(patient_id)
        messages.insert(0, self.system_message)

        # Fetch the patient profile and generate context message
        patient_context_message = await self.create_patient_context_message(
            patient_id
        )
        messages.insert(1, patient_context_message)

        # Add the human input as part of the context
        messages.append(
            {
                "role": "human",
                "content": human_input,
            }
        )

        # Generate a response using the chat model
        ai_response: Any = self.chat_model.invoke(messages)

        # Log token usage
        tokens_used = ai_response.response_metadata.get("token_usage", {}).get(
            "total_tokens", 0
        )
        if tokens_used:
            await PatientTokenUsageLogger.log_usage(
                patient_id=UUID(patient_id),
                tokens_used=tokens_used,
                model_used=self.current_model,
                api_type="openai",
                api_endpoint="/ai-conversation/internal",
            )

        return ai_response.content

    async def generate_report_response(
        self,
        patient_id: str,
        report: Dict[str, Any],
        report_type: str,
        max_recommendations: int = 3,
    ) -> str:
        # human_input = f"""
        # Please analyze the following {report_type} report and provide feedback, including:
        # - Areas for improvement
        # - Positive patterns
        # - Actionable advice tailored to the patient's health goals

        # Report:
        # {report}
        # """
        human_input = f"""
            Please analyze the following {report_type} report and provide feedback in a concise and friendly tone. 
            Include the following:
            - A brief overview of the key insights (2-3 points).
            - Highlight one positive pattern.
            - Provide up to {max_recommendations} actionable recommendations for improvement.
            - Avoid overwhelming details, keeping the response under 300 words.

            Report:
            {report}
            """

        ai_response = await self.generate_temporary_response(
            patient_id=patient_id,
            human_input=human_input,
        )

        return ai_response

    async def _generate_message_suggestions(self, ai_response_content: str):
        suggestion_prompt = (
            f"Based on the response:\n{ai_response_content}\n"
            "Generate 3 to 5 suggested follow-up questions or replies that the user might want to ask. "
            "without suggesting any external apps, tools, or resources. "
            "Keep the suggestions relevant to the ongoing conversation and within the context of this app's capabilities. "
            "Provide helpful, relevant follow-up questions related to health and wellness, staying within the app's context. "
            "Avoid general advice or external recommendations; focus on personalized health insights or support."
        )
        messages = [SystemMessage(content=suggestion_prompt)]

        suggestion_model = self.chat_model.with_structured_output(
            AiResponseSuggestions, strict=True
        )

        try:
            suggestion_response: Any = suggestion_model.invoke(messages)
            suggestions = suggestion_response.suggestions
            print("==> suggestions: ", suggestions)
            return suggestions
        except ValidationError as e:
            print("Error: Response did not match the expected schema", e)
            return None

    async def generate_health_tip_of_the_day(self, patient_id: str):
        patient_context_message = await self.create_patient_context_message(
            patient_id
        )
        messages = [self.system_message, patient_context_message]

        ai_tip_response = self.chat_model.invoke(messages)
        health_tip = ai_tip_response.content

        tokens_used = ai_tip_response.response_metadata.get(
            "token_usage", {}
        ).get("total_tokens", 0)
        if tokens_used:
            await PatientTokenUsageLogger.log_usage(
                patient_id=UUID(patient_id),
                tokens_used=tokens_used,
                model_used=self.current_model,
                api_type="openai",
                api_endpoint="/ai-conversation/health-tip",
            )

        return health_tip

    async def delete_conversation_messages(
        self,
        conversation_id: str,
    ):
        """Deletes all messages for a given conversation."""
        try:
            delete_result = await self.ai_messages_collection.delete_many(
                {"conversation_id": conversation_id}
            )
            return delete_result

        except ValueError as ve:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid input for deleting conversation messages.",
                detail=str(ve),
            )
        except Exception as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="An unexpected error occurred while deleting conversation messages.",
                detail=str(e),
            )
