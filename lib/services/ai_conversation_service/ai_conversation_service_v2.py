import asyncio
from datetime import datetime
import json
from typing import Any, Dict, List, Literal, Optional, Type, Union

from bson import json_util
from decouple import config
from fastapi import status
from langchain.output_parsers import PydanticOutputParser
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_perplexity import ChatPerplexity
from pydantic import SecretStr, ValidationError

from lib.core.constants import ProfileTypeEnum
from lib.core.types import (
    AiConversationMessageTypeLiteral,
    AiConversationRoleLiteral,
    AiConversationTypeLiteral,
    AIModelProviderLiteral,
    GeminiAIModelLiteral,
    OpenAIModelLiteral,
    PerplexityAIModelLiteral,
)
from lib.schemas.ai_conversation_schemas import (
    AiConversationMessage as AiConversationMessageSchema,
)
from lib.schemas.ai_conversation_schemas import (
    AIResponse,
    AIResponseFollowUpQuestions,
)
from lib.schemas.patient import CorePatientProfile
from lib.services.qdrant_search_engine.qdrant_search_engine import (
    QdrantSearchEngine,
)
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.retry_utils import retry_request

from .system_messages.base_system_message import BaseSystemMessage
from .system_messages.care_provider_system_message import (
    CareProviderSystemMessage,
)
from .system_messages.health_tip_system_message import HealthTipSystemMessage
from .system_messages.meal_system_message import MealSystemMessage
from .system_messages.prescription_system_message import (
    PrescriptionSystemMessage,
)
from .system_messages.report_system_message import ReportSystemMessage
from .system_messages.sleep_system_message import SleepSystemMessage
from .system_messages.smbg_system_message import SMBGSystemMessage


class AiConversationServiceV2:
    _SYSTEM_MESSAGE_MAP: Dict[
        AiConversationTypeLiteral, Type[BaseSystemMessage]
    ] = {
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
        qdrant_search_engine: QdrantSearchEngine,
        conversation_type: AiConversationTypeLiteral = "other",
        ai_model_provider: AIModelProviderLiteral = "openai",
        selected_ai_model: Union[
            OpenAIModelLiteral, GeminiAIModelLiteral, PerplexityAIModelLiteral
        ] = "gpt-4o",
    ):
        from lib.dependencies.service_dependencies import (
            get_ai_conversation_messages_collection,
            get_patient_profile_service,
            get_token_usage_service,
        )

        self.qdrant_search_engine = qdrant_search_engine

        self.token_usage_service = get_token_usage_service()
        self.patient_profile_service = get_patient_profile_service()

        self.ai_messages_collection: Any = (
            get_ai_conversation_messages_collection()
        )

        self.selected_ai_model: Union[
            OpenAIModelLiteral, GeminiAIModelLiteral, PerplexityAIModelLiteral
        ] = selected_ai_model
        self.ai_model_provider: AIModelProviderLiteral = ai_model_provider

        if ai_model_provider == "openai":
            self.chat_model = ChatOpenAI(
                model=self.selected_ai_model,  # type: ignore
                temperature=0.5,
                api_key=SecretStr(str(config("OPENAI_API_KEY"))),
            )
        elif ai_model_provider == "perplexity":
            self.chat_model = ChatPerplexity(
                api_key=SecretStr(str(config("PERPLEXITY_API_KEY"))),
                model=self.selected_ai_model,
                temperature=0.5,
                timeout=200,
            )
        else:
            self.chat_model = ChatGoogleGenerativeAI(
                api_key=SecretStr(str(config("GOOGLE_API_KEY"))),
                model=self.selected_ai_model,
                temperature=0.5,
            )

        self.output_parser = PydanticOutputParser(pydantic_object=AIResponse)
        format_instructions = self.output_parser.get_format_instructions()

        self.structured_model = self.chat_model.with_structured_output(
            AIResponse, include_raw=True
        )
        self.system_message = self._get_initial_system_message(
            conversation_type, format_instructions
        )
        # pprint(self.system_message)

    def _get_initial_system_message(
        self,
        conversation_type: AiConversationTypeLiteral,
        format_instructions: Optional[str] = None,
    ) -> SystemMessage:
        return self._SYSTEM_MESSAGE_MAP.get(
            conversation_type, BaseSystemMessage
        )().get_system_message(format_instructions=format_instructions)

    async def add_message_to_conversation(
        self,
        user_id: str,
        user_type: ProfileTypeEnum,
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
            user_type=user_type,
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            role=role,
            content=content,
            message_type=message_type,
            exclude_from_frontend=exclude_from_frontend,
            follow_up_questions=follow_up_questions,
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

        messages = await self.ai_messages_collection.aggregate(
            pipeline
        ).to_list(length=None)
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

        messages = await self.ai_messages_collection.aggregate(
            pipeline
        ).to_list(length=None)
        return await self._process_messages(messages)

    async def create_patient_context_message(
        self, patient_id: str, prefix: str = "Patient Profile:"
    ) -> HumanMessage:
        patient = await self.patient_profile_service.fetch_patient_profile(
            patient_id=patient_id,
            detailed=True,
            include_health_data=True,
        )  # type: ignore
        patient_profile_json = CorePatientProfile.from_orm(
            patient
        ).model_dump()
        return HumanMessage(
            content=f"{prefix}\n```json\n{patient_profile_json}\n```"
        )

    def enforce_alternation(self, messages: list) -> list:
        filtered = [messages[0]]  # Keep system message
        for msg in messages[1:]:
            if not filtered:
                filtered.append(msg)
                continue

            last_type = filtered[-1].type
            if msg.type != last_type:  # Only add if alternates
                filtered.append(msg)
        return filtered

    async def generate_response(
        self,
        patient_id: str,
        user_id: str,
        user_type: ProfileTypeEnum,
        conversation_id: str,
        human_input: str,
    ) -> Dict:
        await self.add_message_to_conversation(
            user_id,
            user_type,
            conversation_id,
            "care-provider",
            "human",
            human_input,
        )

        messages: Any = [self.system_message]

        messages.append(
            await self.create_patient_context_message(
                patient_id, prefix="Patient Profile: "
            )
        )

        history = [*await self.fetch_conversation_messages(conversation_id)]
        messages += history

        patient_data = await self.qdrant_search_engine.search(
            human_input, 100, patient_id=patient_id
        )
        filter = patient_data["filter_applied"]
        filter_text = json.dumps(filter, ensure_ascii=False, indent=2)

        patient_points = patient_data["results"]
        patient_texts = []

        for point in patient_points:
            text = json.dumps(point.payload, ensure_ascii=False)
            patient_texts.append(text)

        # Combine all texts into one string or multiple system messages
        context_text = (
            f"Patient data (limited to {len(patient_points)} records):\n\n"
            f"Filters applied:\n{filter_text}\n\n"
            f"Data considered:\n" + "\n\n".join(patient_texts)
        )

        # Then append to messages
        messages.append({"role": "system", "content": context_text})

        filtered_messages = (
            self.enforce_alternation(messages)
            if self.ai_model_provider == "perplexity"
            else messages
        )

        try:
            # ai_response: Any = retry_request(
            #     self.structured_model.invoke,
            #     input=filtered_messages,
            # )
            ai_response: Any = self.structured_model.invoke(
                input=filtered_messages
            )

            parsed_response: AIResponse = ai_response.get("parsed", {})
            follow_up_questions = await self.generate_followup_questions(
                parsed_response.response
            )

            ai_message_data = await self.add_message_to_conversation(
                user_id,
                user_type,
                conversation_id,
                "care-provider",
                "ai",
                parsed_response.response,
                message_type="markdown",
                follow_up_questions=follow_up_questions,
                metadata={
                    "citations": parsed_response.citations,
                    "confidence_score": parsed_response.confidence_score,
                    "tags": parsed_response.tags,
                },
            )

            usage_metadata = ai_response["raw"].usage_metadata

            # Log token usage
            if usage_metadata:
                await self.token_usage_service.log_usage(
                    user_id=user_id,
                    user_type=user_type,
                    input_tokens=usage_metadata["input_tokens"],
                    output_tokens=usage_metadata["output_tokens"],
                    cached_input_tokens=usage_metadata.get(
                        "cached_input_tokens"
                    ),
                    model_used=self.selected_ai_model,
                    model_provider=self.ai_model_provider,
                    api_endpoint="/ai-conversation/respond",
                )  # type: ignore

            return ai_message_data
        except Exception as e:
            print(f"Error generating AI response: {str(e)}")
            raise_http_exception(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Failed to generate AI response.",
                detail=str(e),
            )

    async def generate_followup_questions(self, ai_response_content: str):
        prompt = f"""
        Based on this health response:
        {ai_response_content}
        
        Generate between 3-5 follow-up questions that meet these criteria:
        1. Must be complete questions phrased in FIRST PERSON ("I" form)
        2. Minimum 5 words per question
        3. Directly related to the health content
        4. Avoid yes/no questions
        5. Useful for further health understanding
        6. Should sound like something the PATIENT would ask, not the AI

        Examples:
        - "What specific foods should I focus on to improve these readings?"
        - "How might adjusting my exercise timing affect these glucose patterns?"
        - "When should I be most concerned about these levels?"
        """

        messages = [
            SystemMessage(
                content="You are a health assistant helping a patient formulate good follow-up questions."
            ),
            HumanMessage(content=prompt),
        ]
        question_model = self.chat_model.with_structured_output(
            AIResponseFollowUpQuestions, strict=True
        )

        try:
            response: Any = question_model.invoke(messages)
            return response.questions
        except ValidationError as e:
            print("Error: Response did not match the expected schema", e)
            return None

    async def _build_care_provider_context(
        self, conversation_id: str, patient_id: str
    ):

        history = await self.fetch_conversation_messages(conversation_id)
        return [
            *history,
        ]

    async def _build_standard_context(
        self, conversation_id: str, patient_id: str
    ):
        if conversation_id.endswith("-patient"):
            return await self.fetch_user_entire_conversation_messages(
                patient_id
            )
        return await self.fetch_conversation_messages(conversation_id)
