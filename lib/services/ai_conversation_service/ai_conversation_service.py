import asyncio
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Type, Union

from bson import json_util
from decouple import config
from fastapi import status
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
# from langchain_perplexity import ChatPerplexity
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
from .system_messages.weight_loss_agent_system_message import (
    WeightLossAgentSystemMessage,
)


class AiConversationService:
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
        "weight-loss-agent": WeightLossAgentSystemMessage,
    }

    def __init__(
        self,
        conversation_type: AiConversationTypeLiteral = "other",
        ai_model_provider: AIModelProviderLiteral = "openai",
        selected_ai_model: Union[
            OpenAIModelLiteral, GeminiAIModelLiteral, PerplexityAIModelLiteral
        ] = "gpt-4o",
    ):
        from lib.dependencies.service_dependencies import (
            get_ai_conversation_messages_collection,
            get_cgm_report_collection,
            get_fitness_report_collection,
            get_meal_report_collection,
            get_patient_profile_service,
            get_sleep_report_collection,
            get_token_usage_service,
        )

        self.token_usage_service = get_token_usage_service()
        self.patient_profile_service = get_patient_profile_service()

        self.ai_messages_collection: Any = (
            get_ai_conversation_messages_collection()
        )
        self.cgm_report_collection: Any = get_cgm_report_collection()
        self.fitness_report_collection: Any = get_fitness_report_collection()
        self.meal_report_collection: Any = get_meal_report_collection()
        self.sleep_report_collection: Any = get_sleep_report_collection()

        self.selected_ai_model: Union[
            OpenAIModelLiteral, GeminiAIModelLiteral, PerplexityAIModelLiteral
        ] = selected_ai_model
        self.ai_model_provider: AIModelProviderLiteral = ai_model_provider
        self.user_type = (
            ProfileTypeEnum.CARE_PROVIDER
            if conversation_type == "care-provider"
            else ProfileTypeEnum.PATIENT
        )

        if ai_model_provider == "openai":
            self.chat_model = ChatOpenAI(
                model=self.selected_ai_model,  # type: ignore
                temperature=0.5,
                api_key=SecretStr(str(config("OPENAI_API_KEY"))),
            )
        # elif ai_model_provider == "perplexity":
        #     self.chat_model = ChatPerplexity(
        #         api_key=SecretStr(str(config("PERPLEXITY_API_KEY"))),
        #         model=self.selected_ai_model,
        #         temperature=0.5,
        #         timeout=200,
        #     )
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
            user_type=self.user_type,
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

    async def get_patient_reports(
        self,
        patient_id: str,
        report_types: Optional[
            List[Literal["sleep", "meal", "fitness", "cgm"]]
        ] = None,
        date_range: Optional[
            Dict[Literal["start_date", "end_date"], datetime]
        ] = None,
        limit_per_report: Optional[int] = None,
        return_raw: bool = False,
    ):
        # Default to all report types if none specified
        if report_types is None:
            report_types = ["sleep", "meal", "fitness", "cgm"]

        # Common match filter
        match_filter: Dict = {"patient_id": patient_id}

        # Add date range filter if provided
        if date_range:
            match_filter["start_date"] = {"$gte": date_range["start_date"]}
            match_filter["end_date"] = {"$lte": date_range["end_date"]}

        # Common pipeline stages
        pipeline = [
            {"$match": match_filter},
            {"$sort": {"start_date": -1}},  # Most recent first
        ]

        if limit_per_report:
            pipeline.append({"$limit": limit_per_report})

        if not return_raw:
            pipeline.append({"$addFields": {"_id": {"$toString": "$_id"}}})

        # Prepare coroutines for requested report types
        coroutines = []

        if "sleep" in report_types:
            coroutines.append(
                self.sleep_report_collection.aggregate(
                    pipeline.copy()
                ).to_list(length=None)
            )
        if "meal" in report_types:
            coroutines.append(
                self.meal_report_collection.aggregate(pipeline.copy()).to_list(
                    length=None
                )
            )
        if "fitness" in report_types:
            coroutines.append(
                self.fitness_report_collection.aggregate(
                    pipeline.copy()
                ).to_list(length=None)
            )
        if "cgm" in report_types:
            coroutines.append(
                self.cgm_report_collection.aggregate(pipeline.copy()).to_list(
                    length=None
                )
            )

        # Execute all queries in parallel
        results = await asyncio.gather(*coroutines)

        # Build the response dictionary
        response = {
            "sleep_reports": [],
            "meal_reports": [],
            "fitness_reports": [],
            "cgm_reports": [],
        }

        result_index = 0
        if "sleep" in report_types:
            response["sleep_reports"] = results[result_index]
            result_index += 1
        if "meal" in report_types:
            response["meal_reports"] = results[result_index]
            result_index += 1
        if "fitness" in report_types:
            response["fitness_reports"] = results[result_index]
            result_index += 1
        if "cgm" in report_types:
            response["cgm_reports"] = results[result_index]

        return response

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
        conversation_id: str,
        human_input: str,
        conversation_type: AiConversationTypeLiteral,
        additional_context: Optional[Any] = None,
        *,
        api_endpoint: Optional[str] = None,
    ) -> Dict:
        await self.add_message_to_conversation(
            user_id,
            conversation_id,
            conversation_type,
            "human",
            human_input,
        )

        # System + profile context
        messages: Any = [self.system_message]
        profile_prefix = (
            "My Profile:"
            if conversation_type == "patient"
            else "Patient Profile:"
        )
        messages.append(
            await self.create_patient_context_message(
                patient_id, prefix=profile_prefix
            )
        )

        if additional_context:
            if isinstance(additional_context, dict):
                context_str = json_util.dumps(additional_context, indent=2)
            else:
                context_str = str(additional_context)

            messages.append(
                HumanMessage(content=f"User Context:\n{context_str}")
            )

        # Handle conversation type specific context
        if conversation_type == "care-provider":
            messages += await self._build_care_provider_context(
                conversation_id, patient_id
            )
        else:  # patient or others
            messages += await self._build_standard_context(
                conversation_id, patient_id
            )

        filtered_messages = (
            self.enforce_alternation(messages)
            if self.ai_model_provider == "perplexity"
            else messages
        )

        try:
            ai_response: Any = retry_request(
                self.structured_model.invoke,
                input=filtered_messages,
            )
            # ai_response: Any = self.structured_model.invoke(input=filtered_messages)

            parsed_response: AIResponse = ai_response.get("parsed", {})
            follow_up_questions = await self.generate_followup_questions(
                parsed_response.response
            )

            ai_message_data = await self.add_message_to_conversation(
                user_id,
                conversation_id,
                conversation_type,
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
                    user_type=self.user_type,
                    input_tokens=usage_metadata["input_tokens"],
                    output_tokens=usage_metadata["output_tokens"],
                    cached_input_tokens=usage_metadata.get(
                        "cached_input_tokens"
                    ),
                    model_used=self.selected_ai_model,
                    model_provider=self.ai_model_provider,
                    api_endpoint=api_endpoint or "/ai-conversation/respond",
                )  # type: ignore

            return ai_message_data
        except Exception as e:
            print(f"Error generating AI response: {str(e)}")
            raise_http_exception(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Failed to generate AI response.",
                detail=str(e),
            )

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
        ai_response: Any = self.structured_model.invoke(messages)
        parsed_response: AIResponse = ai_response.get("parsed", {})

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
                api_endpoint="/ai-conversation/internal",
            )  # type: ignore

        return parsed_response.response

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

    async def generate_health_tip_for_patient(self, patient_id: str):
        patient_context_message = await self.create_patient_context_message(
            patient_id
        )
        messages = [self.system_message, patient_context_message]

        ai_response: Any = self.structured_model.invoke(messages)
        parsed_response: AIResponse = ai_response.get("parsed", {})

        health_tip = parsed_response.response
        usage_metadata = ai_response["raw"].usage_metadata

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
            )  # type: ignore

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

    async def _build_care_provider_context(
        self, conversation_id: str, patient_id: str
    ):
        # patient_reports = await self.get_patient_reports(
        #     patient_id, return_raw=True, limit_per_report=1
        # )
        history = await self.fetch_conversation_messages(conversation_id)
        return [
            # HumanMessage(
            #     content=f"Patient Reports:\n{json_util.dumps(patient_reports, indent=2)}"
            # ),
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
