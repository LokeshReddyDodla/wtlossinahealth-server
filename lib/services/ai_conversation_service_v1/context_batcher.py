import json
from typing import Any, AsyncGenerator, Dict, List, Optional
from collections import defaultdict
import tiktoken

from lib.services.ai_conversation_service_v1.context_builder import (
    AIConversationContextBuilder,
)


class AIConversationContextBatcher:
    def __init__(
        self,
        context_builder: AIConversationContextBuilder,
        model_name: str = "gpt-4.1-mini",
        max_tokens: int = 48000,  # keep a buffer under model limit
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

    def _chunk_items_by_tokens(
        self, items: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """
        Chunk a list of items safely so that each chunk does not exceed max_tokens.
        """
        chunks = []
        current_chunk = []
        current_tokens = 0

        for item in items:
            item_text = json.dumps(item, ensure_ascii=False)
            item_tokens = self._count_tokens(item_text)

            if item_tokens > self.max_tokens:
                # Single item exceeds token limit — split by lines
                lines = item_text.split("\n")
                sub_chunk = []
                sub_tokens = 0
                for line in lines:
                    line_tokens = self._count_tokens(line)
                    if sub_tokens + line_tokens > self.max_tokens:
                        if sub_chunk:
                            chunks.append([json.loads("\n".join(sub_chunk))])
                        sub_chunk = [line]
                        sub_tokens = line_tokens
                    else:
                        sub_chunk.append(line)
                        sub_tokens += line_tokens
                if sub_chunk:
                    chunks.append([json.loads("\n".join(sub_chunk))])
                continue

            if current_tokens + item_tokens > self.max_tokens:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = [item]
                current_tokens = item_tokens
            else:
                current_chunk.append(item)
                current_tokens += item_tokens

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    async def generate_batches(
        self,
        patient_ids: List[str],
        conversation_id: str,
        human_input: str,
        include_history: bool = True,
        report_id: Optional[str] = None,
        merge_across_data_types: bool = True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Yield token-safe batches of context grouped by patient and data_type.
        Can optionally merge small data_type chunks into larger batches.
        """
        # Slice patient_ids into manageable groups
        for i in range(0, len(patient_ids), self.patient_batch_size):
            batch_patient_ids = patient_ids[i : i + self.patient_batch_size]

            # Build context for the batch of patients
            context_data = await self.context_builder.build_context(
                patient_ids=batch_patient_ids,
                report_id=report_id,
                conversation_id=conversation_id,
                human_input=human_input,
                include_history=include_history,
            )

            context_items = context_data.get("context_items", [])
            filter_applied = context_data.get("filter_applied", {})
            recent_messages = context_data.get("conversation", {}).get(
                "recent", []
            )

            # ---- GROUP BY PATIENT -> DATA_TYPE ----
            grouped = defaultdict(lambda: defaultdict(list))
            for item in context_items:
                pid = item.get("patient_id", "unknown")
                dtype = item.get("data_type", "unknown")
                grouped[pid][dtype].append(item)

            # ---- FIRST: chunk each data_type per patient ----
            all_chunks = []
            for pid, dtype_dict in grouped.items():
                for dtype, items in dtype_dict.items():
                    chunks = self._chunk_items_by_tokens(items)
                    for idx, chunk in enumerate(chunks):
                        all_chunks.append(
                            {
                                "patient_id": pid,
                                "data_type": dtype,
                                "chunk_index": idx,
                                "chunk_items": chunk,
                            }
                        )

            # ---- SECOND: optionally merge chunks across data_types while respecting token limit ----
            if merge_across_data_types:
                merged_chunks = []
                current_chunk_items = []
                current_chunk_meta = {
                    "patient_ids": set(),
                    "data_types": set(),
                }
                current_tokens = 0

                for c in all_chunks:
                    chunk_text = "\n".join(
                        json.dumps(obj, ensure_ascii=False)
                        for obj in c["chunk_items"]
                    )
                    chunk_tokens = self._count_tokens(chunk_text)

                    if (
                        current_tokens + chunk_tokens > self.max_tokens
                        and current_chunk_items
                    ):
                        merged_chunks.append(
                            {
                                "batch_patient_ids": list(
                                    current_chunk_meta["patient_ids"]
                                ),
                                "data_types": list(
                                    current_chunk_meta["data_types"]
                                ),
                                "context_items": current_chunk_items,
                            }
                        )
                        current_chunk_items = c["chunk_items"]
                        current_chunk_meta = {
                            "patient_ids": {c["patient_id"]},
                            "data_types": {c["data_type"]},
                        }
                        current_tokens = chunk_tokens
                    else:
                        current_chunk_items.extend(c["chunk_items"])
                        current_chunk_meta["patient_ids"].add(c["patient_id"])
                        current_chunk_meta["data_types"].add(c["data_type"])
                        current_tokens += chunk_tokens

                # yield any remaining merged chunk
                if current_chunk_items:
                    merged_chunks.append(
                        {
                            "batch_patient_ids": list(
                                current_chunk_meta["patient_ids"]
                            ),
                            "data_types": list(
                                current_chunk_meta["data_types"]
                            ),
                            "context_items": current_chunk_items,
                        }
                    )
            else:
                merged_chunks = [
                    {
                        "batch_patient_ids": [c["patient_id"]],
                        "data_types": [c["data_type"]],
                        "context_items": c["chunk_items"],
                    }
                    for c in all_chunks
                ]

            # ---- BUILD CONTEXT STRING AND YIELD ----
            for idx, mc in enumerate(merged_chunks):
                context_payload_text = "\n".join(
                    json.dumps(obj, ensure_ascii=False)
                    for obj in mc["context_items"]
                )
                full_context = (
                    f"Patient IDs: {mc['batch_patient_ids']}\n"
                    f"Data Types: {mc['data_types']}\n"
                    f"Context Data:\n{context_payload_text}"
                )

                if include_history and recent_messages:
                    full_context += "\n\n---\n\nConversation History:\n"
                    full_context += "\n".join(
                        f"{m['role']}: {m['content']}" for m in recent_messages
                    )

                total_tokens = self._count_tokens(full_context)

                yield {
                    "batch_patient_ids": mc["batch_patient_ids"],
                    "data_types": mc["data_types"],
                    "chunk_index": idx,
                    "context": full_context,
                    "context_items": mc["context_items"],
                    "filter_applied": filter_applied,
                    "token_count": total_tokens,
                }
