from typing import Literal

import litellm
from decouple import config
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import tiktoken


_GEMINI_API_KEY = str(config("GEMINI_API_KEY", default="")) or None

CHUNK_SIZE = 50  # number of texts per batch request
MAX_TOKENS_PER_TEXT = 3000  # conservative limit for chunking long texts

OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"
GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
# litellm addresses Gemini embeddings under the gemini/ provider prefix.
_GEMINI_LITELLM_MODEL = f"gemini/{GEMINI_EMBEDDING_MODEL}"

EmbeddingProvider = Literal["gemini", "openai"]
DEFAULT_EMBEDDING_PROVIDER: EmbeddingProvider = "openai"


def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    enc = tiktoken.get_encoding(encoding_name)
    return len(enc.encode(text))


def _normalize_provider(provider: EmbeddingProvider) -> EmbeddingProvider:
    normalized = provider.lower().strip()
    if normalized not in ("gemini", "openai"):
        raise ValueError(f"Unsupported embedding provider: {provider}")
    return normalized  # type: ignore[return-value]


async def _aembedding(model: str, texts: list[str]) -> list[list[float]]:
    kwargs: dict = {"model": model, "input": texts}
    if model.startswith("gemini/") and _GEMINI_API_KEY:
        kwargs["api_key"] = _GEMINI_API_KEY
    response = await litellm.aembedding(**kwargs)
    return [item["embedding"] for item in response.data]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
)
async def _embed_openai_batch(texts: list[str]) -> list[list[float]]:
    return await _aembedding(OPENAI_EMBEDDING_MODEL, texts)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
)
async def _embed_gemini_batch(texts: list[str]) -> list[list[float]]:
    return await _aembedding(_GEMINI_LITELLM_MODEL, texts)


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
    model = OPENAI_EMBEDDING_MODEL if resolved_provider == "openai" else _GEMINI_LITELLM_MODEL
    embeddings = await _aembedding(model, [text])
    return embeddings[0]
