from typing import Any, Dict, List
from uuid import UUID

from decouple import config
from fastapi import HTTPException
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from pymongo import MongoClient
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.types import (AiConversationMessageTypeLiteral,
                            AiConversationRoleLiteral,
                            AiConversationTypeLiteral, OpenAIModelLiteral)
from lib.schemas.ai_conversation_message import \
    AiConversationMessage as AiConversationMessageSchema
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

        self.current_model = model
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

        if conversation_type == "meal_analysis":
            return SystemMessage(
                content="""
                You are an AI strictly focused on meal analysis for diabetic and obese patients. Respond only with information related to the current meal, its nutrition, and dietary insights in markdown format. Avoid mentioning any unrelated meals or mixing multiple meals from different times of the day.

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

        elif conversation_type == "prescription_analysis":
            return SystemMessage(
                content="You are an AI strictly focused on prescription analysis. Respond only with information related to prescriptions, medical details, and relevant insights in markdown format. Avoid any response that includes your origin, development, or unrelated topics."
            )

        elif conversation_type == "report_analysis":
            return SystemMessage(
                content="You are an AI strictly focused on report analysis. Provide insights only about health reports and their content in markdown format. Avoid any response that includes your origin, development, or unrelated topics."
            )
        return SystemMessage(
            content="You are a knowledgeable assistant. Respond only in the context of the ongoing conversation and provide all responses in markdown format. Avoid mentioning anything beyond the specific task."
        )

    def add_message_to_conversation(
        self,
        patient_id: str,
        conversation_id: str,
        role: AiConversationRoleLiteral,
        content: str,
        message_type: AiConversationMessageTypeLiteral = "text",
        exclude_from_frontend: bool = False,
    ):
        """Add a message to the conversation."""
        message_data = AiConversationMessageSchema(
            patient_id=patient_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            message_type=message_type,
            exclude_from_frontend=exclude_from_frontend,
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

    async def create_patient_context_message(
        self, patient_profile_service: PatientProfileService, patient_id: str
    ) -> SystemMessage:
        """Generate a system message containing the patient's profile."""
        patient = await patient_profile_service.fetch_patient_profile(
            patient_id=patient_id, detailed=True
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
        patient_profile_service: PatientProfileService,
    ) -> Dict:
        self.add_message_to_conversation(
            patient_id, conversation_id, "human", human_input
        )

        # Fetch all messages to provide context, inserting the system message at the start
        messages = self.fetch_conversation_messages(conversation_id)
        messages.insert(0, self.system_message)

        # Fetch the patient profile and generate context message
        patient_context_message = await self.create_patient_context_message(
            patient_profile_service, patient_id
        )
        messages.insert(1, patient_context_message)

        # Generate a response using the chat model
        ai_response: Any = self.chat_model.invoke(messages)
        ai_message_data = self.add_message_to_conversation(
            patient_id,
            conversation_id,
            "ai",
            ai_response.content,
            message_type="markdown",
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
                api_endpoint="conversation_response",
            )

        return ai_message_data

    def delete_conversation_messages(self, conversation_id: str):
        """Deletes all messages for a given conversation."""
        try:
            delete_result = self.messages_collection.delete_many(
                {"conversation_id": conversation_id}
            )
            return delete_result
        except Exception as e:
            print(f"Failed to delete conversation messages: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Failed to delete conversation messages",
            )
