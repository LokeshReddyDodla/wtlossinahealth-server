from typing import List
from openai import AsyncOpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import tiktoken


openai_client = AsyncOpenAI()

MAX_TOKENS_PER_REQUEST = 8000  # safe margin for text-embedding-3-large
CHUNK_SIZE = 50  # number of texts per batch request


def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    enc = tiktoken.get_encoding(encoding_name)
    return len(enc.encode(text))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
)
async def embed_chunk(texts: List[str]) -> List[List[float]]:
    response = await openai_client.embeddings.create(
        model="text-embedding-3-large",
        input=texts,
    )
    return [item.embedding for item in response.data]


async def embed_text_batch_safe(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []

    safe_texts = []
    for t in texts:
        tokens = count_tokens(t)
        if tokens > 3000:
            chunk_size = len(t) // ((tokens // 3000) + 1)
            for i in range(0, len(t), chunk_size):
                safe_texts.append(t[i : i + chunk_size])
        else:
            safe_texts.append(t)

    # Process in batches
    embeddings: List[List[float]] = []
    for i in range(0, len(safe_texts), CHUNK_SIZE):
        batch = safe_texts[i : i + CHUNK_SIZE]
        batch_embeddings = await embed_chunk(batch)
        embeddings.extend(batch_embeddings)

    return embeddings


async def embed_text(text: str) -> list[float]:
    response = await openai_client.embeddings.create(
        model="text-embedding-3-large",
        input=text,
    )
    return response.data[0].embedding
