from typing import List, Dict, Any, AsyncGenerator
import tiktoken


class AIConversationContextBatcher:
    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        max_tokens: int = 12000,  # model limit buffer (keep under 128k for gpt-4o)
        patient_batch_size: int = 50,
    ):
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.patient_batch_size = patient_batch_size
        self.encoder = tiktoken.encoding_for_model(model_name)

    def _count_tokens(self, text: str) -> int:
        return len(self.encoder.encode(text))

    async def _fetch_patient_contexts(
        self, patient_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Fetch context (e.g. from Redis, Postgres, Mongo, or Qdrant)
        for all given patient_ids. Replace this with your actual logic.
        """
        # placeholder example
        contexts = []
        for pid in patient_ids:
            contexts.append(
                {
                    "patient_id": pid,
                    "profile": f"Profile data for {pid}",
                    "recent_meals": f"Meal summary for {pid}",
                }
            )
        return contexts

    async def _build_context_string(
        self, patient_contexts: List[Dict[str, Any]]
    ) -> str:
        return "\n\n".join(
            f"Patient ID: {ctx['patient_id']}\n"
            f"Profile: {ctx['profile']}\n"
            f"Meals: {ctx['recent_meals']}"
            for ctx in patient_contexts
        )

    async def generate_batches(
        self, patient_ids: List[str]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Yields safe context batches:
        - slices patient_ids into small batches
        - chunks context text dynamically if tokens exceed limit
        """

        # 1️⃣ Slice patient_ids first
        for i in range(0, len(patient_ids), self.patient_batch_size):
            batch_ids = patient_ids[i : i + self.patient_batch_size]
            patient_contexts = await self._fetch_patient_contexts(batch_ids)
            context_text = await self._build_context_string(patient_contexts)

            # 2️⃣ Token-count-based chunking
            tokens = self._count_tokens(context_text)
            if tokens <= self.max_tokens:
                yield {
                    "batch_patient_ids": batch_ids,
                    "context": context_text,
                    "token_count": tokens,
                }
            else:
                # split context dynamically by text lines
                lines = context_text.split("\n\n")
                current_chunk, current_tokens = [], 0
                for line in lines:
                    line_tokens = self._count_tokens(line)
                    if current_tokens + line_tokens > self.max_tokens:
                        yield {
                            "batch_patient_ids": batch_ids,
                            "context": "\n\n".join(current_chunk),
                            "token_count": current_tokens,
                        }
                        current_chunk = [line]
                        current_tokens = line_tokens
                    else:
                        current_chunk.append(line)
                        current_tokens += line_tokens

                # yield the last chunk
                if current_chunk:
                    yield {
                        "batch_patient_ids": batch_ids,
                        "context": "\n\n".join(current_chunk),
                        "token_count": current_tokens,
                    }
