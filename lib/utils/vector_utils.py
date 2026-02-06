import asyncio
from typing import Literal

from decouple import config
from google import genai
from openai import AsyncOpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import tiktoken


openai_client = AsyncOpenAI()
gemini_client = genai.Client(api_key=str(config("GOOGLE_API_KEY")))

CHUNK_SIZE = 50  # number of texts per batch request
MAX_TOKENS_PER_TEXT = 3000  # conservative limit for chunking long texts

OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"
GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"

EmbeddingProvider = Literal["gemini", "openai"]
DEFAULT_EMBEDDING_PROVIDER: EmbeddingProvider = "gemini"


def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    enc = tiktoken.get_encoding(encoding_name)
    return len(enc.encode(text))


def _normalize_provider(provider: EmbeddingProvider) -> EmbeddingProvider:
    normalized = provider.lower().strip()
    if normalized not in ("gemini", "openai"):
        raise ValueError(f"Unsupported embedding provider: {provider}")
    return normalized  # type: ignore[return-value]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
)
async def _embed_openai_batch(texts: list[str]) -> list[list[float]]:
    response = await openai_client.embeddings.create(
        model=OPENAI_EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
)
async def _embed_gemini_batch(texts: list[str]) -> list[list[float]]:
    response = await asyncio.to_thread(
        gemini_client.models.embed_content,
        model=GEMINI_EMBEDDING_MODEL,
        contents=texts,
    )
    return [embedding.values for embedding in response.embeddings]


async def embed_text_batch_safe(
    texts: list[str],
    provider: EmbeddingProvider = DEFAULT_EMBEDDING_PROVIDER,
) -> list[list[float]]:
    if not texts:
        return []

    safe_texts = []
    for t in texts:
        tokens = count_tokens(t)
        if tokens > MAX_TOKENS_PER_TEXT:
            chunk_size = len(t) // ((tokens // MAX_TOKENS_PER_TEXT) + 1)
            for i in range(0, len(t), chunk_size):
                safe_texts.append(t[i : i + chunk_size])
        else:
            safe_texts.append(t)

    # Process in batches
    embeddings: list[list[float]] = []
    resolved_provider = _normalize_provider(provider)
    for i in range(0, len(safe_texts), CHUNK_SIZE):
        batch = safe_texts[i : i + CHUNK_SIZE]
        if resolved_provider == "openai":
            batch_embeddings = await _embed_openai_batch(batch)
        else:
            batch_embeddings = await _embed_gemini_batch(batch)
        embeddings.extend(batch_embeddings)

    return embeddings


async def embed_text(
    text: str, provider: EmbeddingProvider = DEFAULT_EMBEDDING_PROVIDER
) -> list[float]:
    resolved_provider = _normalize_provider(provider)
    if resolved_provider == "openai":
        response = await openai_client.embeddings.create(
            model=OPENAI_EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding

    response = await asyncio.to_thread(
        gemini_client.models.embed_content,
        model=GEMINI_EMBEDDING_MODEL,
        contents=[text],
    )
    return response.embeddings[0].values
