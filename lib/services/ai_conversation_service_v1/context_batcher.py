import json
from typing import List, Dict, Any, AsyncGenerator
import tiktoken

from lib.services.ai_conversation_service_v1.context_builder import (
    AIConversationContextBuilder,
)


class AIConversationContextBatcher:
    def __init__(
        self,
        context_builder: AIConversationContextBuilder,
        model_name: str = "gpt-4.1-mini",
        max_tokens: int = 48000,  # model limit buffer (keep under 128k for gpt-4o)
        patient_batch_size: int = 10,
    ):
        self.context_builder = context_builder
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.patient_batch_size = patient_batch_size

        try:
            self.encoder = tiktoken.encoding_for_model(model_name)
        except KeyError:
            self.encoder = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(self, text: str) -> int:
        return len(self.encoder.encode(text))

    async def generate_batches(
        self,
        patient_ids: List[str],
        conversation_id: str,
        human_input: str,
        include_history: bool = True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Dynamically yields safe, token-limited context batches.
        - Splits patient_ids into small batches.
        - Builds context for each batch.
        - Automatically chunks the context text if it exceeds token limits.
        """

        # Slice patient_ids into manageable groups
        for i in range(0, len(patient_ids), self.patient_batch_size):
            batch_ids = patient_ids[i : i + self.patient_batch_size]

            # Build full context for this patient batch
            context_data = await self.context_builder.build_context(
                patient_ids=batch_ids,
                conversation_id=conversation_id,
                human_input=human_input,
                include_history=include_history,
            )

            context_items = context_data.get("context_items", [])
            filter_applied = context_data.get("filter_applied", {})
            recent_messages = context_data.get("conversation", {}).get(
                "recent", []
            )

            # Represent the context as clean JSON strings
            context_payload_text = "\n".join(
                json.dumps(item, ensure_ascii=False) for item in context_items
            )

            # Combine context, filters, and conversation
            full_context = (
                f"Context data:\n{context_payload_text}\n\n"
                f"Filters applied: {json.dumps(filter_applied, ensure_ascii=False)}"
            )

            if include_history and recent_messages:
                full_context += "\n\n---\n\nConversation History:\n"
                full_context += "\n".join(
                    f"{m['role']}: {m['content']}" for m in recent_messages
                )

            # Check token usage
            total_tokens = self._count_tokens(full_context)
            if total_tokens <= self.max_tokens:
                yield {
                    "batch_patient_ids": batch_ids,
                    "context": full_context,
                    "context_items": context_items,
                    "token_count": total_tokens,
                }
            else:
                # Dynamic chunking (splits large context safely)
                lines = full_context.split("\n\n")
                current_chunk, current_tokens = [], 0

                for line in lines:
                    line_tokens = self._count_tokens(line)
                    # Start a new chunk if this line would overflow
                    if current_tokens + line_tokens > self.max_tokens:
                        yield {
                            "batch_patient_ids": batch_ids,
                            "context": "\n\n".join(current_chunk),
                            "context_items": context_items,
                            "token_count": current_tokens,
                        }
                        current_chunk = [line]
                        current_tokens = line_tokens
                    else:
                        current_chunk.append(line)
                        current_tokens += line_tokens

                # yield any remaining context
                if current_chunk:
                    yield {
                        "batch_patient_ids": batch_ids,
                        "context": "\n\n".join(current_chunk),
                        "context_items": context_items,
                        "token_count": current_tokens,
                    }
