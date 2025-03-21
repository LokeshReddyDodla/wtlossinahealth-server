from typing import Any, Dict, List, Optional
from uuid import UUID

from decouple import config
from fastapi import status
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr, ValidationError

from lib.core.constants import AI_RESPONSE_SAFETY_DISCLAIMER, ProfileTypeEnum
from lib.core.types import (AiConversationMessageTypeLiteral,
                            AiConversationRoleLiteral,
                            AiConversationTypeLiteral, OpenAIModelLiteral)
from lib.schemas.ai_conversation_schemas import \
    AiConversationMessage as AiConversationMessageSchema
from lib.schemas.ai_conversation_schemas import (AIResponse,
                                                 AiResponseSuggestions)
from lib.schemas.patient import CorePatientProfile
from lib.services.patient_profile_service import PatientProfileService
from lib.services.token_usage_service import TokenUsageService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.retry_utils import retry_request

from .system_messages.base_system_message import BaseSystemMessage
from .system_messages.health_tip_system_message import HealthTipSystemMessage
from .system_messages.meal_system_message import MealSystemMessage
from .system_messages.prescription_system_message import \
    PrescriptionSystemMessage
from .system_messages.report_system_message import ReportSystemMessage
from .system_messages.sleep_system_message import SleepSystemMessage
from .system_messages.smbg_system_message import SMBGSystemMessage


class AiConversationService:
    def __init__(
        self,
        conversation_type: AiConversationTypeLiteral = "other",
        model: OpenAIModelLiteral = "gpt-4o",
    ):
        from lib.core.container import container

        self.token_usage_service: Any = container.resolve(TokenUsageService)
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
        self.structured_model = self.chat_model.with_structured_output(
            AIResponse, include_raw=True
        )
        self.system_message = self._get_initial_system_message(
            conversation_type
        )

    def _get_initial_system_message(
        self, conversation_type: AiConversationTypeLiteral
    ) -> SystemMessage:
        """Returns the initial system message based on conversation type."""

        if conversation_type == "meal":
            return MealSystemMessage().get_system_message()
        elif conversation_type == "smbg":
            return SMBGSystemMessage().get_system_message()
        elif conversation_type == "sleep":
            return SleepSystemMessage().get_system_message()
        elif conversation_type == "prescription":
            return PrescriptionSystemMessage().get_system_message()
        elif conversation_type == "report":
            return ReportSystemMessage().get_system_message()
        elif conversation_type == "health-tip":
            return HealthTipSystemMessage().get_system_message()

        return BaseSystemMessage().get_system_message()

    async def add_message_to_conversation(
        self,
        patient_id: str,
        conversation_id: str,
        conversation_type: AiConversationTypeLiteral,
        role: AiConversationRoleLiteral,
        content: str,
        message_type: AiConversationMessageTypeLiteral = "text",
        exclude_from_frontend: bool = False,
        follow_up_questions: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
    ):
        message_data = AiConversationMessageSchema(
            patient_id=patient_id,
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            role=role,
            content=content,
            message_type=message_type,
            exclude_from_frontend=exclude_from_frontend,
            reply_suggestions=follow_up_questions,
            metadata=metadata,
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

        # Generate a structured response using the chat model
        ai_response = retry_request(
            self.structured_model.invoke,
            input=messages,
        )
        parsed_response: AIResponse = ai_response.get("parsed", {})

        response = parsed_response.response
        follow_up_questions = (
            parsed_response.follow_up_questions
            if include_reply_suggestions
            else None
        )

        ai_message_data = await self.add_message_to_conversation(
            patient_id,
            conversation_id,
            conversation_type,
            "ai",
            response,
            message_type="markdown",
            follow_up_questions=follow_up_questions,
            metadata={
                "sources": parsed_response.sources,
                "confidence_score": parsed_response.confidence_score,
                "tags": parsed_response.tags,
            },
        )

        usage_metadata = ai_response["raw"].usage_metadata

        # Log token usage
        if usage_metadata:
            await self.token_usage_service.log_usage(
                user_id=UUID(patient_id),
                user_type=ProfileTypeEnum.PATIENT,
                input_tokens=usage_metadata["input_tokens"],
                output_tokens=usage_metadata["output_tokens"],
                cached_input_tokens=usage_metadata.get("cached_input_tokens"),
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
        usage_metadata = ai_response.usage_metadata

        # Log token usage
        if usage_metadata:
            await self.token_usage_service.log_usage(
                user_id=UUID(patient_id),
                user_type=ProfileTypeEnum.PATIENT,
                input_tokens=usage_metadata["input_tokens"],
                output_tokens=usage_metadata["output_tokens"],
                cached_input_tokens=usage_metadata.get("cached_input_tokens"),
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
            return suggestions
        except ValidationError as e:
            print("Error: Response did not match the expected schema", e)
            return None

    async def generate_health_tip_of_the_day(self, patient_id: str):
        patient_context_message = await self.create_patient_context_message(
            patient_id
        )
        messages = [self.system_message, patient_context_message]

        ai_tip_response: Any = self.chat_model.invoke(messages)
        health_tip = ai_tip_response.content
        usage_metadata = ai_tip_response.usage_metadata

        # Log token usage
        if usage_metadata:
            await self.token_usage_service.log_usage(
                user_id=UUID(patient_id),
                user_type=ProfileTypeEnum.PATIENT,
                input_tokens=usage_metadata["input_tokens"],
                output_tokens=usage_metadata["output_tokens"],
                cached_input_tokens=usage_metadata.get("cached_input_tokens"),
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
