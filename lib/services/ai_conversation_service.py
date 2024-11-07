from typing import Any, Dict, List, Optional
from uuid import UUID

from decouple import config
from fastapi import HTTPException
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr, ValidationError
from pymongo import MongoClient
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.types import (AiConversationMessageTypeLiteral,
                            AiConversationRoleLiteral,
                            AiConversationTypeLiteral, OpenAIModelLiteral)
from lib.schemas.ai_conversation_schemas import \
    AiConversationMessage as AiConversationMessageSchema
from lib.schemas.ai_conversation_schemas import AiResponseSuggestions
from lib.schemas.patient import CorePatientProfile
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.patient_token_usage_logger import PatientTokenUsageLogger

MONGO_URL = config("MONGO_URL", default="mongodb://localhost:27017")
MONGO_DB_NAME = config("MONGO_DB_NAME", default="aihealth")


class AiConversationService:
    def __init__(
        self,
        conversation_type: AiConversationTypeLiteral = "other",
        model: OpenAIModelLiteral = "gpt-4o",
    ):

        self.current_model: OpenAIModelLiteral = model
        self.mongo_client = MongoClient(str(MONGO_URL))
        self.db = self.mongo_client[str(MONGO_DB_NAME)]
        self.messages_collection = self.db["ai_conversation_messages"]

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
                "You are a knowledgeable health assistant and an expert in managing diabetes and obesity. "
                "Respond in a friendly and respectful tone, offering the best possible advice tailored to the patient's profile. "
                "Use your expertise to recommend low-GI, high-fiber foods and provide practical, culturally relevant suggestions. "
                "Ensure your responses align with the patient's health goals, focusing on nutrition, lifestyle, and overall well-being. "
                "Provide all responses in markdown format and avoid mentioning anything beyond the specific task or conversation context."
                "Avoid any response that includes your origin, development, or unrelated topics."
            )
        )

    def add_message_to_conversation(
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
        """Add a message to the conversation."""
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

        result = self.messages_collection.insert_one(message_data)
        message_data["_id"] = str(result.inserted_id)
        return message_data

    def add_messages_to_conversation(
        self,
        messages: List[AiConversationMessageSchema],
    ):
        """Batch inserts multiple messages into a conversation."""
        message_data = [message.model_dump() for message in messages]
        self.messages_collection.insert_many(message_data)

    def fetch_conversation_messages(
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

        messages_cursor = self.messages_collection.aggregate(pipeline)

        if return_raw:
            return list(messages_cursor)

        messages = []
        for message in messages_cursor:
            if message["role"] == "system":
                messages.append(SystemMessage(content=message["content"]))
            elif message["role"] == "human":
                messages.append(HumanMessage(content=message["content"]))
            elif message["role"] == "ai":
                messages.append(AIMessage(content=message["content"]))

        return messages

    def fetch_all_user_conversation_messages(
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

        messages_cursor = self.messages_collection.aggregate(pipeline)

        if return_raw:
            return list(messages_cursor)

        messages = []
        for message in messages_cursor:
            if message["role"] == "system":
                messages.append(SystemMessage(content=message["content"]))
            elif message["role"] == "human":
                messages.append(HumanMessage(content=message["content"]))
            elif message["role"] == "ai":
                messages.append(AIMessage(content=message["content"]))

        return messages

    async def create_patient_context_message(
        self, patient_profile_service: PatientProfileService, patient_id: str
    ) -> SystemMessage:
        """Generate a system message containing the patient's profile."""
        patient = await patient_profile_service.fetch_patient_profile(
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
        patient_profile_service: PatientProfileService,
        include_reply_suggestions: bool = True,
    ) -> Dict:
        self.add_message_to_conversation(
            patient_id,
            conversation_id,
            conversation_type,
            "human",
            human_input,
        )

        # Fetch all messages to provide context, inserting the system message at the start
        if conversation_id == f"{patient_id}-custom":
            messages = self.fetch_all_user_conversation_messages(patient_id)
        else:
            messages = self.fetch_conversation_messages(conversation_id)
        messages.insert(0, self.system_message)

        # Fetch the patient profile and generate context message
        patient_context_message = await self.create_patient_context_message(
            patient_profile_service, patient_id
        )
        messages.insert(1, patient_context_message)

        # Generate a response using the chat model
        ai_response: Any = self.chat_model.invoke(messages)

        reply_suggestions = None
        if include_reply_suggestions:
            reply_suggestions = await self._generate_message_suggestions(
                ai_response.content
            )

        ai_message_data = self.add_message_to_conversation(
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

    async def generate_health_tip_of_the_day(
        self, patient_id: str, patient_profile_service: PatientProfileService
    ):
        patient_context_message = await self.create_patient_context_message(
            patient_profile_service, patient_id
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

    def delete_conversation_messages(
        self,
        conversation_id: str,
    ):
        """Deletes all messages for a given conversation."""
        try:

            delete_result = self.messages_collection.delete_many(
                {"conversation_id": conversation_id}
            )
            return delete_result

        except ValueError as ve:
            print(f"Invalid input: {str(ve)}")
            raise HTTPException(
                status_code=400,
                detail="Invalid input: Either conversation_id or reference_id must be provided.",
            )
        except Exception as e:
            print(f"Failed to delete conversation messages: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Failed to delete conversation messages",
            )
