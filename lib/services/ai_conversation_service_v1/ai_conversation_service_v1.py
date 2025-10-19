from collections import defaultdict
import json
import math
import pprint
from typing import Dict, Set, Type, Union

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
from lib.schemas.ai_conversation_schemas import AIResponse, Citation
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


class AIConversationServiceV1:
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
        self.context_batcher = AIConversationContextBatcher(
            context_builder=context_builder,
            model_name=selected_ai_model,
            max_tokens=48000,
            patient_batch_size=10,
        )

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

    async def generate_response(
        self,
        patient_ids: List[str],
        user_id: str,
        user_type: ProfileTypeEnum,
        conversation_id: str,
        human_input: str,
    ):
        try:
            await self.add_message_to_conversation(
                user_id,
                user_type,
                conversation_id,
                "care-provider",
                "human",
                human_input,
            )

            all_batch_responses: list[dict] = []
            total_token_usage = defaultdict(int)

            # ---- Generate batches ----
            async for batch in self.context_batcher.generate_batches(
                patient_ids,
                conversation_id,
                human_input,
                include_history=True,
            ):
                batch_ids = batch["batch_patient_ids"]
                batch_context = batch["context"]

                # Skip if batch has no real context
                if not batch_context.strip() or not batch["context_items"]:
                    print(
                        f"Skipping batch {batch_ids} — no real data available"
                    )
                    continue

                messages = [
                    self.system_message,
                    SystemMessage(content=batch_context),
                    HumanMessage(content=human_input),
                ]

                if self.ai_model_provider == "perplexity":
                    messages = self._enforce_alternation(messages)

                ai_response: Any = self.structured_model.invoke(input=messages)
                parsed: AIResponse = ai_response.get("parsed", {})
                usage = getattr(ai_response["raw"], "usage_metadata", {}) or {}

                all_batch_responses.append(
                    {
                        "batch_patient_ids": batch_ids,
                        "response_text": parsed.response,
                        "citations": parsed.citations,
                        "confidence_score": parsed.confidence_score,
                        "tags": parsed.tags,
                        "token_usage": usage,
                    }
                )

                # Accumulate token usage
                self._accumulate_usage(total_token_usage, usage)

            print(all_batch_responses)

            if all_batch_responses:
                # ---- Only summarize if multiple batches ----
                if len(all_batch_responses) > 1:
                    summarized: Any = await self._summarize_batches(
                        all_batch_responses, human_input
                    )
                    summary_parsed: AIResponse = summarized.get("parsed", {})
                    summary_usage = getattr(summarized["raw"], "usage_metadata", {}) or {}  # type: ignore

                    # Accumulate summary token usage
                    self._accumulate_usage(total_token_usage, summary_usage)
                else:
                    batch = all_batch_responses[0]
                    summary_parsed = AIResponse(
                        response=batch["response_text"],
                        citations=batch.get("citations", []),
                        confidence_score=batch.get("confidence_score"),
                        tags=batch.get("tags", []),
                    )
            else:
                summary_parsed = AIResponse(
                    response="No patient data available to provide insights at this time.",
                    citations=[],
                    confidence_score=None,
                    tags=[],
                )

            # ---- Save AI message ----
            ai_message_data = await self.add_message_to_conversation(
                user_id=user_id,
                user_type=user_type,
                conversation_id=conversation_id,
                conversation_type="care-provider",
                role="ai",
                content=summary_parsed.response,
                message_type="markdown",
                metadata={
                    "citations": summary_parsed.citations,
                    "confidence_score": summary_parsed.confidence_score,
                    "tags": summary_parsed.tags,
                },
            )

            # ---- Log total token usage ----
            if total_token_usage:
                await self.token_usage_service.log_usage(
                    user_id=user_id,
                    user_type=user_type,
                    input_tokens=total_token_usage["input_tokens"],
                    output_tokens=total_token_usage["output_tokens"],
                    cached_input_tokens=total_token_usage.get(
                        "cached_input_tokens"
                    ),
                    model_used=self.selected_ai_model,
                    model_provider=self.ai_model_provider,
                    api_endpoint="/care-provider/ai/conversation/ask",
                )  # type: ignore

            return ai_message_data
        except Exception as e:
            print(
                f"[AIConversationServiceV1] Error generating AI response: {e}"
            )
            raise_http_exception(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Failed to generate AI response.",
                detail=str(e),
            )

    async def _summarize_batches(
        self, batch_responses: list[dict], human_input: str
    ):
        combined_texts = []
        for i, b in enumerate(batch_responses):
            text = b.get("response_text", "")
            combined_texts.append(f"### Batch {i+1}\n{text}")

        merged_batches_text = "\n\n".join(combined_texts)

        summarization_system_prompt = """
        You are a medical data summarizer.
        You will receive multiple AI-generated batch analyses about different groups of patients.

        Your task:
        - Merge overlapping or repetitive insights.
        - Keep all critical, unique information.
        - Summarize overall patterns, trends, and common issues across patients.
        - Maintain clinical accuracy, empathy, and Markdown formatting.
        - Produce the final structured response using the same schema (AIResponse).
        - Include combined citations and relevant tags.
        - End with: "Please consult a healthcare professional for personalized advice."
        """

        messages = [
            SystemMessage(content=summarization_system_prompt),
            SystemMessage(content=f"User query: {human_input}"),
            SystemMessage(
                content=f"Batch responses:\n\n{merged_batches_text}"
            ),
        ]

        summarized_ai_response = self.structured_model.invoke(input=messages)

        return summarized_ai_response

    def _accumulate_usage(self, total_usage: dict, usage: dict):
        total_usage["input_tokens"] += usage.get("input_tokens", 0)
        total_usage["output_tokens"] += usage.get("output_tokens", 0)
        total_usage["cached_input_tokens"] += usage.get(
            "cached_input_tokens", 0
        )
