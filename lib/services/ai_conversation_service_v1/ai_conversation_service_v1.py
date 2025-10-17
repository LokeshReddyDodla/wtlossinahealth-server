import json
import math
from typing import Dict, Type, Union

from langchain_openai import ChatOpenAI
from tiktoken import encoding_for_model
import tiktoken
from lib.core.constants import ProfileTypeEnum
from lib.core.types import (
    AIModelProviderLiteral,
    AiConversationMessageTypeLiteral,
    AiConversationRoleLiteral,
    AiConversationTypeLiteral,
    GeminiAIModelLiteral,
    OpenAIModelLiteral,
    PerplexityAIModelLiteral,
)
from typing import Any, Dict, List, Literal, Optional, Type, Union
from fastapi import status


from decouple import config

from langchain.output_parsers import PydanticOutputParser
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_perplexity import ChatPerplexity
from pydantic import SecretStr
from lib.schemas.ai_conversation_schemas import AIResponse
from lib.services.ai_conversation_service_v1.context_batcher import (
    AIConversationContextBatcher,
)
from lib.services.ai_conversation_service_v1.context_builder import (
    AIConversationContextBuilder,
)
from lib.services.ai_conversation_service_v1.system_messages.base_system_message import (
    BaseSystemMessage,
)
from lib.services.ai_conversation_service_v1.system_messages.care_provider_system_message import (
    CareProviderSystemMessage,
)
from lib.services.ai_conversation_service_v1.system_messages.health_tip_system_message import (
    HealthTipSystemMessage,
)
from lib.services.ai_conversation_service_v1.system_messages.meal_system_message import (
    MealSystemMessage,
)
from lib.services.ai_conversation_service_v1.system_messages.prescription_system_message import (
    PrescriptionSystemMessage,
)
from lib.services.ai_conversation_service_v1.system_messages.report_system_message import (
    ReportSystemMessage,
)
from lib.services.ai_conversation_service_v1.system_messages.sleep_system_message import (
    SleepSystemMessage,
)
from lib.services.ai_conversation_service_v1.system_messages.smbg_system_message import (
    SMBGSystemMessage,
)
from lib.schemas.ai_conversation_schemas import (
    AiConversationMessage as AiConversationMessageSchema,
)
from lib.utils.http_exceptions import raise_http_exception


class AiConversationServiceV1:
    MAX_MODEL_TOKENS = 128_000  # adjust per model (e.g., 128k for GPT-4.1)
    SAFE_LIMIT = int(MAX_MODEL_TOKENS * 0.8)

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
        context_builder: AIConversationContextBuilder,
        conversation_type: AiConversationTypeLiteral = "other",
        ai_model_provider: AIModelProviderLiteral = "openai",
        selected_ai_model: Union[
            OpenAIModelLiteral, GeminiAIModelLiteral, PerplexityAIModelLiteral
        ] = "gpt-4.1-mini",
    ):
        from lib.dependencies.service_dependencies import (
            get_token_usage_service,
            get_ai_conversation_messages_collection,
        )

        self.context_builder = context_builder

        self.token_usage_service = get_token_usage_service()
        self.ai_messages_collection = get_ai_conversation_messages_collection()

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

        result = await self.ai_messages_collection.insert_one(message_data)  # type: ignore
        message_data["_id"] = str(result.inserted_id)
        return message_data

    def _enforce_alternation(self, messages: list) -> list:
        filtered = [messages[0]]  # Keep system message
        for msg in messages[1:]:
            if not filtered:
                filtered.append(msg)
                continue

            last_type = filtered[-1].type
            if msg.type != last_type:  # Only add if alternates
                filtered.append(msg)
        return filtered

    def _process_messages(self, messages: List[Dict]) -> List[Any]:
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

    def estimate_token_count(
        self, data: Any, model: str = "gpt-4o-mini"
    ) -> int:
        if not data:
            return 0

        if isinstance(data, (dict, list)):
            text = json.dumps(data, ensure_ascii=False)
        else:
            text = str(data)

        try:
            encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(text))
        except Exception:
            return math.ceil(
                len(text) / 4
            )  # fallback rough estimate: ~4 chars per token

    def _chunk_context_items(
        self, items: List[Any], chunk_size: int = 5
    ) -> List[List[Any]]:
        return [
            items[i : i + chunk_size] for i in range(0, len(items), chunk_size)
        ]

    async def _prepare_hybrid_batches(
        self, patient_context_map: Dict[str, List[Dict]]
    ) -> List[List[Dict[str, List[Dict]]]]:
        """
        Build dynamic batches across patients, and chunk within if a single patient's context is too big.
        """
        batches = []
        current_batch = []
        current_tokens = 0

        for patient_id, context_items in patient_context_map.items():
            tokens_for_patient = self.estimate_token_count(context_items)

            # case 1: a single patient's context is too big — chunk within
            if tokens_for_patient > self.SAFE_LIMIT:
                chunks = self._chunk_context_items(context_items, chunk_size=5)
                for chunk in chunks:
                    sub_tokens = self.estimate_token_count(chunk)
                    if current_tokens + sub_tokens > self.SAFE_LIMIT:
                        batches.append(current_batch)
                        current_batch = []
                        current_tokens = 0
                    current_batch.append({patient_id: chunk})
                    current_tokens += sub_tokens

            # case 2: normal patient — add normally
            else:
                if current_tokens + tokens_for_patient > self.SAFE_LIMIT:
                    batches.append(current_batch)
                    current_batch = []
                    current_tokens = 0
                current_batch.append({patient_id: context_items})
                current_tokens += tokens_for_patient

        if current_batch:
            batches.append(current_batch)

        return batches

    async def _generate_batched_response(
        self,
        batches: List[List[Dict[str, List[Dict]]]],
        human_input: str,
        conversation_id: str,
    ) -> List[Dict]:
        all_responses = []

        for batch_index, batch in enumerate(batches, start=1):
            batch_context_items = []
            for patient_chunk in batch:
                for _, context_items in patient_chunk.items():
                    batch_context_items.extend(context_items)

            # Build message chain
            context_payload_text = "\n".join(
                json.dumps(item, ensure_ascii=False)
                for item in batch_context_items
            )
            messages = [
                self.system_message,
                SystemMessage(
                    content=f"Context batch #{batch_index}:\n{context_payload_text}"
                ),
                HumanMessage(content=human_input),
            ]

            try:
                ai_response = self.structured_model.invoke(input=messages)
                parsed_response = ai_response.get("parsed", {})
                all_responses.append(parsed_response)
                print(
                    f"✅ Processed batch {batch_index} with {len(batch_context_items)} context items."
                )
            except Exception as e:
                print(f"⚠️ Error in batch {batch_index}: {e}")

        return all_responses

    async def generate_response(
        self,
        patient_ids: List[str],
        user_id: str,
        user_type: ProfileTypeEnum,
        conversation_id: str,
        human_input: str,
    ):

        try:
            batcher = AIConversationContextBatcher(
                model_name="gpt-4o-mini",
                max_tokens=12000,
                patient_batch_size=50,
            )
            patient_ids = [f"patient-{i}" for i in range(1, 250)]  # example

            async for batch in batcher.generate_batches(patient_ids):
                print(
                    f"🧩 Batch (IDs={len(batch['batch_patient_ids'])}) | Tokens={batch['token_count']}"
                )
                print(batch["context"][:200], "...\n")

        # # Save the human message
        # await self.add_message_to_conversation(
        #     user_id,
        #     user_type,
        #     conversation_id,
        #     "care-provider",
        #     "human",
        #     human_input,
        # )

        # # Start message chain
        # messages: list[Any] = [self.system_message]

        # # Build context
        # context_data = await self.context_builder.build_context(
        #     patient_ids=patient_ids,
        #     conversation_id=conversation_id,
        #     human_input=human_input,
        #     include_history=True,
        # )

        # context_items = context_data.get("context_items", [])
        # filter_applied = context_data.get("filter_applied", {})
        # recent_messages = context_data.get("conversation", {}).get(
        #     "recent", []
        # )

        # # Add context payloads as one big system message
        # context_payload_text = "\n".join(
        #     json.dumps(item, ensure_ascii=False) for item in context_items
        # )
        # messages.append(
        #     SystemMessage(
        #         content=f"Context data:\n{context_payload_text}\nFilters applied: {json.dumps(filter_applied, ensure_ascii=False)}"
        #     )
        # )

        # # Add conversation history
        # messages.extend(self._process_messages(recent_messages))

        # # Add current human input
        # messages.append(HumanMessage(content=human_input))

        # # enforce alternation if you want to ensure clean format
        # messages = (
        #     self._enforce_alternation(messages)
        #     if self.ai_model_provider == "perplexity"
        #     else messages
        # )

        # tokens = self.estimate_token_count(messages)
        # print(f"Estimated tokens: {tokens}")

        # try:
        #     # ai_response: Any = retry_request(
        #     #     self.structured_model.invoke,
        #     #     input=filtered_messages,
        #     # )
        #     ai_response: Any = self.structured_model.invoke(input=messages)
        #     parsed_response: AIResponse = ai_response.get("parsed", {})
        #     follow_up_questions = None

        #     ai_message_data = await self.add_message_to_conversation(
        #         user_id,
        #         user_type,
        #         conversation_id,
        #         "care-provider",
        #         "ai",
        #         parsed_response.response,
        #         message_type="markdown",
        #         follow_up_questions=follow_up_questions,
        #         metadata={
        #             "citations": parsed_response.citations,
        #             "confidence_score": parsed_response.confidence_score,
        #             "tags": parsed_response.tags,
        #         },
        #     )

        #     usage_metadata = ai_response["raw"].usage_metadata
        #     print("==> usage_metadata:", usage_metadata)
        #     if usage_metadata:
        #         await self.token_usage_service.log_usage(
        #             user_id=user_id,
        #             user_type=user_type,
        #             input_tokens=usage_metadata["input_tokens"],
        #             output_tokens=usage_metadata["output_tokens"],
        #             cached_input_tokens=usage_metadata.get(
        #                 "cached_input_tokens"
        #             ),
        #             model_used=self.selected_ai_model,
        #             model_provider=self.ai_model_provider,
        #             api_endpoint="/ai-conversation/respond",
        #         )  # type: ignore

        #     return ai_message_data

        except Exception as e:
            print(f"Error generating AI response: {str(e)}")
            raise_http_exception(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Failed to generate AI response.",
                detail=str(e),
            )
