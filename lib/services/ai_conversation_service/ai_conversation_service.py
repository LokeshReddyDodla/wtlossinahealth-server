from pprint import pprint
from typing import Any, Dict, List, Optional, Type, Union

from decouple import config
from fastapi import status
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr, ValidationError

from lib.core.constants import ProfileTypeEnum
from lib.core.types import (AiConversationMessageTypeLiteral,
                            AiConversationRoleLiteral,
                            AiConversationTypeLiteral, AIModelProviderLiteral,
                            GeminiAIModelLiteral, OpenAIModelLiteral)
from lib.schemas.ai_conversation_schemas import \
    AiConversationMessage as AiConversationMessageSchema
from lib.schemas.ai_conversation_schemas import (AIResponse,
                                                 AiResponseSuggestions)
from lib.schemas.patient import CorePatientProfile
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.retry_utils import retry_request

from .system_messages.base_system_message import BaseSystemMessage
from .system_messages.care_provider_system_message import \
    CareProviderSystemMessage
from .system_messages.health_tip_system_message import HealthTipSystemMessage
from .system_messages.meal_system_message import MealSystemMessage
from .system_messages.prescription_system_message import \
    PrescriptionSystemMessage
from .system_messages.report_system_message import ReportSystemMessage
from .system_messages.sleep_system_message import SleepSystemMessage
from .system_messages.smbg_system_message import SMBGSystemMessage


class AiConversationService:
    _SYSTEM_MESSAGE_MAP: Dict[AiConversationTypeLiteral, Type[BaseSystemMessage]] = {
        "meal": MealSystemMessage,
        "smbg": SMBGSystemMessage,
        "sleep": SleepSystemMessage,
        "prescription": PrescriptionSystemMessage,
        "report": ReportSystemMessage,
        "health-tip": HealthTipSystemMessage,
        "care-provider": CareProviderSystemMessage,
    }

    def __init__(
        self,
        conversation_type: AiConversationTypeLiteral = "other",
        ai_model_provider: AIModelProviderLiteral = "openai",
        selected_ai_model: Union[OpenAIModelLiteral, GeminiAIModelLiteral] = "gpt-4o",
    ):
        from lib.dependencies.service_dependencies import (
            get_ai_conversation_messages_collection,
            get_patient_profile_service, get_token_usage_service)

        self.token_usage_service = get_token_usage_service()
        self.patient_profile_service = get_patient_profile_service()
        self.ai_messages_collection: Any = get_ai_conversation_messages_collection()
        self.selected_ai_model: Union[OpenAIModelLiteral, GeminiAIModelLiteral] = (
            selected_ai_model
        )
        self.ai_model_provider: AIModelProviderLiteral = ai_model_provider
        self.user_type = (
            ProfileTypeEnum.CARE_PROVIDER
            if conversation_type == "care-provider"
            else ProfileTypeEnum.PATIENT
        )

        if ai_model_provider == "openai":
            self.chat_model = ChatOpenAI(
                model=self.selected_ai_model,
                temperature=0.5,
                api_key=SecretStr(str(config("OPENAI_API_KEY"))),
            )
        else:
            self.chat_model = ChatGoogleGenerativeAI(
                api_key=SecretStr(str(config("GOOGLE_API_KEY"))),
                model=self.selected_ai_model,
                temperature=0.5,
            )
        self.structured_model = self.chat_model.with_structured_output(
            AIResponse, include_raw=True
        )
        self.system_message = self._get_initial_system_message(conversation_type)
        pprint(self.system_message)

    def _get_initial_system_message(
        self, conversation_type: AiConversationTypeLiteral
    ) -> SystemMessage:
        return self._SYSTEM_MESSAGE_MAP.get(
            conversation_type, BaseSystemMessage
        )().get_system_message()

    async def add_message_to_conversation(
        self,
        user_id: str,
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
            user_id=user_id,
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

    async def _process_messages(self, messages: List[Dict]) -> List[Any]:
        return [
            (
                SystemMessage(content=msg["content"])
                if msg["role"] == "system"
                else (
                    HumanMessage(content=msg["content"])
                    if msg["role"] == "human"
                    else AIMessage(content=msg["content"])
                )
            )
            for msg in messages
        ]

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

        messages = await self.ai_messages_collection.aggregate(pipeline).to_list(
            length=None
        )
        return await self._process_messages(messages)

    async def fetch_user_entire_conversation_messages(
        self,
        user_id: str,
        return_raw: bool = False,
    ) -> List[Any]:
        """Fetch all messages for a given conversation."""
        filters: Any = {"user_id": user_id}
        pipeline = [
            {"$match": filters},
            {"$sort": {"timestamp": 1}},
            {"$addFields": {"_id": {"$toString": "$_id"}}},
        ]

        messages_cursor = self.ai_messages_collection.aggregate(pipeline)
        if return_raw:
            return await messages_cursor.to_list(length=None)

        messages = await self.ai_messages_collection.aggregate(pipeline).to_list(
            length=None
        )
        return await self._process_messages(messages)

    async def create_patient_context_message(
        self, patient_id: str, prefix: str = "Patient Profile:"
    ) -> HumanMessage:
        patient = await self.patient_profile_service.fetch_patient_profile(
            patient_id=patient_id, detailed=True, include_health_data=True
        )
        patient_profile_json = CorePatientProfile.from_orm(patient).model_dump()
        return HumanMessage(content=f"{prefix}\n```json\n{patient_profile_json}\n```")

    async def generate_response(
        self,
        patient_id: str,
        user_id: str,
        conversation_id: str,
        human_input: str,
        conversation_type: AiConversationTypeLiteral,
    ) -> Dict:
        await self.add_message_to_conversation(
            user_id,
            conversation_id,
            conversation_type,
            "human",
            human_input,
        )

        if conversation_type == "care-provider":
            patient_history = await self.fetch_user_entire_conversation_messages(
                user_id
            )
            care_provider_history = await self.fetch_conversation_messages(
                conversation_id
            )
            messages = [*patient_history, *care_provider_history]
        elif conversation_id == f"{patient_id}-custom":
            messages = await self.fetch_user_entire_conversation_messages(patient_id)
        else:
            messages = await self.fetch_conversation_messages(conversation_id)

        messages.insert(0, self.system_message)

        prefix = "My Profile:" if conversation_type == "patient" else "Patient Profile:"
        patient_context_message = await self.create_patient_context_message(
            patient_id, prefix=prefix
        )
        messages.insert(1, patient_context_message)

        ai_response: Any = retry_request(
            self.structured_model.invoke,
            input=messages,
        )
        parsed_response: AIResponse = ai_response.get("parsed", {})

        ai_message_data = await self.add_message_to_conversation(
            user_id,
            conversation_id,
            conversation_type,
            "ai",
            parsed_response.response,
            message_type="markdown",
            follow_up_questions=parsed_response.follow_up_questions,
            metadata={
                # "sources": parsed_response.sources,
                "confidence_score": parsed_response.confidence_score,
                "tags": parsed_response.tags,
            },
        )

        usage_metadata = ai_response["raw"].usage_metadata

        # Log token usage
        if usage_metadata:
            await self.token_usage_service.log_usage(
                user_id=user_id,
                user_type=self.user_type,
                input_tokens=usage_metadata["input_tokens"],
                output_tokens=usage_metadata["output_tokens"],
                cached_input_tokens=usage_metadata.get("cached_input_tokens"),
                model_used=self.selected_ai_model,
                model_provider=self.ai_model_provider,
                api_endpoint="/ai-conversation/respond",
            )

        return ai_message_data

    async def generate_temporary_response(
        self,
        user_id: str,
        patient_id: str,
        human_input: str,
    ) -> str:
        """
        Generate a response without saving any messages to the database.
        """

        messages = await self.fetch_user_entire_conversation_messages(user_id)
        messages.insert(0, self.system_message)

        patient_context_message = await self.create_patient_context_message(patient_id)
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
                user_id=user_id,
                user_type=self.user_type,
                input_tokens=usage_metadata["input_tokens"],
                output_tokens=usage_metadata["output_tokens"],
                cached_input_tokens=usage_metadata.get("cached_input_tokens"),
                model_used=self.selected_ai_model,
                model_provider=self.ai_model_provider,
                api_endpoint="/ai-conversation/internal",
            )

        return ai_response.content

    async def generate_report_response(
        self,
        patient_id: str,
        user_id: str,
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
            user_id=user_id,
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

    async def generate_health_tip_for_patient(self, patient_id: str):
        patient_context_message = await self.create_patient_context_message(patient_id)
        messages = [self.system_message, patient_context_message]

        ai_tip_response: Any = self.chat_model.invoke(messages)
        health_tip = ai_tip_response.content
        usage_metadata = ai_tip_response.usage_metadata

        # Log token usage
        if usage_metadata:
            await self.token_usage_service.log_usage(
                user_id=patient_id,
                user_type=ProfileTypeEnum.PATIENT,
                input_tokens=usage_metadata["input_tokens"],
                output_tokens=usage_metadata["output_tokens"],
                cached_input_tokens=usage_metadata.get("cached_input_tokens"),
                model_used=self.selected_ai_model,
                model_provider=self.ai_model_provider,
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
