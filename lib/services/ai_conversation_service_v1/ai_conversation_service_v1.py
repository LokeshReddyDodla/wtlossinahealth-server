from collections import defaultdict
import time
from typing import Dict, Union

from langchain_openai import ChatOpenAI

from lib.core.constants import ProfileTypeEnum
from lib.core.types import (
    AIModelProviderLiteral,
    GeminiAIModelLiteral,
    OpenAIModelLiteral,
    PerplexityAIModelLiteral,
)
from typing import Any, Dict, List, Optional, Union
from fastapi import status


from decouple import config

from langchain.output_parsers import PydanticOutputParser
from langchain.schema import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr, ValidationError
from lib.schemas.ai_conversation_schemas import AIResponse
from lib.schemas.ai_conversation_v1_schemas import (
    MessageStatusLiteral,
    MessageTypeLiteral,
    RoleLiteral,
    SenderTypeLiteral,
)
from lib.services.ai_conversation_service_v1.context_batcher import (
    AIConversationContextBatcher,
)
from lib.services.ai_conversation_service_v1.context_builder import (
    AIConversationContextBuilder,
)
from lib.services.ai_conversation_service_v1.system_messages.base_system_message import (
    BaseSystemMessage,
)
from lib.schemas.ai_conversation_v1_schemas import (
    AiConversationMessageV1 as AiConversationMessageV1Schema,
)
from lib.utils.http_exceptions import raise_http_exception


class AIConversationServiceV1:
    MAX_MODEL_TOKENS = 128_000  # adjust per model (e.g., 128k for GPT-4.1)
    SAFE_LIMIT = int(MAX_MODEL_TOKENS * 0.5)
    PATIENT_BATCH_SIZE = 10

    def __init__(
        self,
        context_builder: AIConversationContextBuilder,
        ai_model_provider: AIModelProviderLiteral = "openai",
        selected_ai_model: Union[
            OpenAIModelLiteral, GeminiAIModelLiteral
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
            max_tokens=self.SAFE_LIMIT,
            patient_batch_size=self.PATIENT_BATCH_SIZE,
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
        self.system_message = BaseSystemMessage().get_system_message(
            format_instructions=format_instructions
        )

    async def add_message_to_conversation(
        self,
        sender_id: str,
        sender_type: SenderTypeLiteral,
        conversation_id: str,
        conversation_type: str,
        role: RoleLiteral,
        content: str,
        message_type: MessageTypeLiteral = "text",
        hidden_from_ui: bool = False,
        follow_up_questions: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        status: MessageStatusLiteral = "pending",
        error_message: Optional[str] = None,
        model: Optional[str] = None,
        token_usage: Optional[Dict[str, int]] = None,
        latency_ms: Optional[int] = None,
    ):
        try:
            message_data = AiConversationMessageV1Schema(
                sender_id=sender_id,
                sender_type=sender_type,
                conversation_id=conversation_id,
                conversation_type=conversation_type,
                role=role,
                content=content,
                message_type=message_type,
                hidden_from_ui=hidden_from_ui,
                follow_up_questions=follow_up_questions,
                metadata=metadata,
                status=status,
                error_message=error_message,
                model=model,
                token_usage=token_usage,
                latency_ms=latency_ms,
            ).model_dump()

            result = await self.ai_messages_collection.insert_one(message_data)  # type: ignore
            message_data["_id"] = str(result.inserted_id)
            return message_data

        except ValidationError as e:
            print(f"[AIConversationServiceV1] Validation error: {e}")
            raise
        except Exception as e:
            print(f"[AIConversationServiceV1] Failed to insert message: {e}")
            raise

    async def fetch_conversation_messages(
        self,
        conversation_id: str,
        hidden_only: Optional[bool] = False,
        limit: Optional[int] = 100,
        offset: Optional[int] = 0,
    ) -> List[Any]:
        filters: Any = {"conversation_id": conversation_id}

        if hidden_only:
            filters["hidden_from_ui"] = True

        pipeline = [
            {"$match": filters},
            {"$sort": {"created_at": 1}},
            {"$skip": offset},
            {"$limit": limit},
            {"$addFields": {"_id": {"$toString": "$_id"}}},
        ]

        messages_cursor = self.ai_messages_collection.aggregate(pipeline)  # type: ignore
        return await messages_cursor.to_list(length=None)

    async def generate_response(
        self,
        patient_ids: List[str],
        sender_id: str,
        sender_type: SenderTypeLiteral,
        conversation_id: str,
        human_input: str,
        api_endpoint: str,
        report_id: Optional[str] = None,
    ):
        start_time = time.monotonic()
        ai_message_data = None

        try:
            # Log user message
            await self.add_message_to_conversation(
                sender_id=sender_id,
                sender_type=sender_type,
                conversation_id=conversation_id,
                conversation_type="care_provider",
                role="human",
                content=human_input,
                status="success",
            )

            all_batch_responses: list[dict] = []
            total_token_usage = defaultdict(int)

            # ---- Generate batches ----
            async for batch in self.context_batcher.generate_batches(
                patient_ids,
                conversation_id,
                human_input,
                include_history=True,
                report_id=report_id,
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

                ai_response: Any = self.structured_model.invoke(input=messages)
                parsed: AIResponse = ai_response.get("parsed", {})
                usage = getattr(ai_response["raw"], "usage_metadata", {}) or {}

                all_batch_responses.append(
                    {
                        "batch_patient_ids": batch_ids,
                        "context": batch_context,
                        "context_items": batch.get("context_items", []),
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

            # Summarize or fallback
            if all_batch_responses:
                # ---- Only summarize if multiple batches ----
                if len(all_batch_responses) > 1:
                    summarized: Any = await self._summarize_batches(
                        all_batch_responses, human_input
                    )
                    summary_parsed: AIResponse = summarized.get("parsed", {})
                    summary_usage = getattr(summarized["raw"], "usage_metadata", {}) or {}  # type: ignore
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

            latency_ms = int((time.monotonic() - start_time) * 1000)

            # ---- Save AI message ----
            ai_message_data = await self.add_message_to_conversation(
                sender_id="system",
                sender_type="ai",
                conversation_id=conversation_id,
                conversation_type="care_provider",
                role="ai",
                content=summary_parsed.response,
                message_type="markdown",
                metadata={
                    "patient_ids": patient_ids,
                    "batched_contexts": [
                        {
                            "batch_patient_ids": b["batch_patient_ids"],
                            "context": b["context"],
                            "context_items": b.get("context_items", []),
                            "response_text": b["response_text"],
                            "citations": b.get("citations", []),
                            "confidence_score": b.get("confidence_score"),
                            "tags": b.get("tags", []),
                            "token_usage": b.get("token_usage", {}),
                        }
                        for b in all_batch_responses
                    ],
                    "citations": summary_parsed.citations,
                    "confidence_score": summary_parsed.confidence_score,
                    "tags": summary_parsed.tags,
                    "total_batches": len(all_batch_responses),
                    "total_input_tokens": total_token_usage.get(
                        "input_tokens", 0
                    ),
                    "total_output_tokens": total_token_usage.get(
                        "output_tokens", 0
                    ),
                    "total_cached_input_tokens": total_token_usage.get(
                        "cached_input_tokens", 0
                    ),
                    "latency_ms": latency_ms,
                    "model_info": {
                        "model": self.selected_ai_model,
                        "provider": self.ai_model_provider,
                        "api_endpoint": api_endpoint,
                    },
                    "human_input": human_input,
                },
                status="success",
                model=self.selected_ai_model,
                token_usage=total_token_usage,
                latency_ms=latency_ms,
            )

            # ---- Log total token usage ----
            if total_token_usage:
                await self.token_usage_service.log_usage(
                    user_id=sender_id,
                    user_type=ProfileTypeEnum.CARE_PROVIDER,
                    input_tokens=total_token_usage["input_tokens"],
                    output_tokens=total_token_usage["output_tokens"],
                    cached_input_tokens=total_token_usage.get(
                        "cached_input_tokens"
                    ),
                    model_used=self.selected_ai_model,
                    model_provider=self.ai_model_provider,
                    api_endpoint=api_endpoint,
                )  # type: ignore

            return ai_message_data
        except Exception as e:
            print(
                f"[AIConversationServiceV1] Error generating AI response: {e}"
            )
            latency_ms = int((time.monotonic() - start_time) * 1000)

            # 🧨 Save failed AI message
            await self.add_message_to_conversation(
                sender_id="system",
                sender_type="ai",
                conversation_id=conversation_id,
                conversation_type="care_provider",
                role="ai",
                content="Failed to generate AI response.",
                status="failed",
                error_message=str(e),
                model=self.selected_ai_model,
                latency_ms=latency_ms,
                hidden_from_ui=True,
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
