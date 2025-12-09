import asyncio
from collections import defaultdict
import time
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
from bson import ObjectId


def log_time(label, start):
    print(f"[TIMING] {label}: {int((time.monotonic() - start) * 1000)} ms")


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

        # self._setup_model(model=selected_ai_model)

    def _setup_model(
        self,
        model: Union[
            str, OpenAIModelLiteral, GeminiAIModelLiteral
        ] = "gpt-4.1-mini",
    ):
        self.selected_ai_model = model

        # ---- Provider Selection ----
        if model in OpenAIModelLiteral.__args__:
            self.ai_model_provider = "openai"
            self.chat_model = ChatOpenAI(
                model=model,
                temperature=1,
                api_key=SecretStr(str(config("OPENAI_API_KEY"))),
            )
        elif model in GeminiAIModelLiteral.__args__:
            self.ai_model_provider = "gemini"
            self.chat_model = ChatGoogleGenerativeAI(
                model=model,
                temperature=1,
                api_key=SecretStr(str(config("GOOGLE_API_KEY"))),
            )
        else:
            raise ValueError(f"Unknown model: {model}")

        # ---- Structured Output ----
        self.output_parser = PydanticOutputParser(pydantic_object=AIResponse)
        format_instructions = self.output_parser.get_format_instructions()

        self.structured_model = self.chat_model.with_structured_output(
            AIResponse, include_raw=True
        )

        # ---- System Message ----
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
            {
                "$set": {
                    "metadata": {
                        "citations": {"$ifNull": ["$metadata.citations", []]},
                        "confidence_score": "$metadata.confidence_score",
                        "tags": {"$ifNull": ["$metadata.tags", []]},
                    }
                }
            },
        ]

        messages_cursor = self.ai_messages_collection.aggregate(pipeline)  # type: ignore
        return await messages_cursor.to_list(length=None)

    async def fetch_message_by_id(
        self, message_id: str
    ) -> Optional[Dict[str, Any]]:
        message = await self.ai_messages_collection.find_one(  # type: ignore
            {"id": message_id}
        )
        if message:
            message["_id"] = str(message["_id"])
        return message

    async def generate_response(
        self,
        patient_ids: List[str],
        sender_id: str,
        sender_type: SenderTypeLiteral,
        conversation_id: str,
        human_input: str,
        api_endpoint: str,
        report_id: Optional[str] = None,
        model: Optional[str] = "gpt-4.1-mini",
    ):
        total_start = time.monotonic()
        ai_message_data = None

        print("\n========== AI RESPONSE START ==========")

        if model:
            t = time.monotonic()
            self._setup_model(model=model)
            log_time("setup_model()", t)

        try:
            # Log human message
            t = time.monotonic()
            await self.add_message_to_conversation(
                sender_id=sender_id,
                sender_type=sender_type,
                conversation_id=conversation_id,
                conversation_type="care_provider",
                role="human",
                content=human_input,
                status="success",
            )
            log_time("add_message_to_conversation(human)", t)

            total_token_usage = defaultdict(int)

            # ---- Generate ALL batches eagerly ----
            t = time.monotonic()
            batches = [
                batch
                async for batch in self.context_batcher.generate_batches(
                    patient_ids,
                    conversation_id,
                    human_input,
                    include_history=True,
                    report_id=report_id,
                )
            ]
            log_time("generate_batches()", t)
            print(f"[INFO] Total batches generated: {len(batches)}")

            # ---- Process all batches in PARALLEL ----
            t = time.monotonic()
            batch_results = await asyncio.gather(
                *[self._process_single_batch(b, human_input) for b in batches]
            )
            log_time("parallel batch processing", t)

            # ---- Filter ----
            usable_batches = [b for b in batch_results if not b["skip"]]
            print(f"[INFO] Usable batches: {len(usable_batches)}")

            # ---- Accumulate usage ----
            t = time.monotonic()
            for b in usable_batches:
                self._accumulate_usage(total_token_usage, b["token_usage"])
            log_time("accumulate_usage()", t)

            # ---- Summarize or fallback ----
            if usable_batches:
                if len(usable_batches) > 1:
                    t = time.monotonic()
                    summarized: Any = await self._summarize_batches(
                        usable_batches, human_input
                    )
                    log_time("_summarize_batches()", t)

                    summary_parsed = summarized.get("parsed", {})
                    summary_usage = (
                        getattr(summarized["raw"], "usage_metadata", {}) or {}
                    )
                    self._accumulate_usage(total_token_usage, summary_usage)
                else:
                    batch = usable_batches[0]
                    summary_parsed = AIResponse(
                        response=batch["response_text"],
                        citations=batch.get("citations", []),
                        confidence_score=batch.get("confidence_score"),
                        tags=batch.get("tags", []),
                    )
            else:
                summary_parsed = AIResponse(
                    response="No patient data available.",
                    citations=[],
                    confidence_score=None,
                    tags=[],
                )

            latency_ms = int((time.monotonic() - total_start) * 1000)

            # ---- Save AI final message ----
            t = time.monotonic()
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
                    "batched_contexts": usable_batches,
                    "citations": summary_parsed.citations,
                    "confidence_score": summary_parsed.confidence_score,
                    "tags": summary_parsed.tags,
                    "total_batches": len(usable_batches),
                    "total_input_tokens": total_token_usage["input_tokens"],
                    "total_output_tokens": total_token_usage["output_tokens"],
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
            log_time("add_message_to_conversation(ai)", t)

            # ---- Log token usage ----
            if total_token_usage:
                t = time.monotonic()
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
                log_time("token_usage_service.log_usage()", t)

            log_time("TOTAL generate_response()", total_start)
            print("========== AI RESPONSE END ==========\n")

            return ai_message_data

        except Exception as e:
            print(f"[ERROR] generate_response failed: {e}")

            latency_ms = int((time.monotonic() - total_start) * 1000)
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
            raise

    async def _process_single_batch(self, batch, human_input):
        batch_start = time.monotonic()
        batch_ids = batch["batch_patient_ids"]

        print(f"\n--- PROCESSING BATCH {batch_ids} ---")

        batch_context = batch["context"]

        if not batch_context.strip() or not batch.get("context_items"):
            print(f"[SKIP] empty context for batch {batch_ids}")
            log_time(f"batch {batch_ids} (skipped)", batch_start)
            return {
                "skip": True,
                "batch_patient_ids": batch_ids,
                "reason": "empty_context",
            }

        # Prepare messages
        message_start = time.monotonic()
        messages = [
            self.system_message,
            SystemMessage(content=batch_context),
            HumanMessage(content=human_input),
        ]
        log_time(f"prepare messages for batch {batch_ids}", message_start)

        # Model call
        invoke_start = time.monotonic()
        try:
            ai_response = self.structured_model.invoke(messages)  # type: ignore
        except Exception as e:
            print(f"[ERROR] model invoke failed for batch {batch_ids}: {e}")
            log_time(f"batch {batch_ids} invoke_failed", invoke_start)
            return {
                "skip": True,
                "batch_patient_ids": batch_ids,
                "reason": f"invoke_failed: {e}",
            }

        log_time(f"model call for batch {batch_ids}", invoke_start)

        # Parse results
        parse_start = time.monotonic()
        parsed = ai_response.get("parsed", {})
        usage = getattr(ai_response["raw"], "usage_metadata", {}) or {}
        log_time(f"parse results for batch {batch_ids}", parse_start)

        log_time(f"TOTAL batch {batch_ids}", batch_start)

        return {
            "skip": False,
            "batch_patient_ids": batch_ids,
            "context": batch_context,
            "context_items": batch.get("context_items", []),
            "filter_applied": batch.get("filter_applied", {}),
            "response_text": parsed.response,
            "citations": parsed.citations,
            "confidence_score": parsed.confidence_score,
            "tags": parsed.tags,
            "token_usage": usage,
        }

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
