from typing import List
from openai import AsyncOpenAI

openai_client = AsyncOpenAI()


async def embed_text(text: str) -> list[float]:
    response = await openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding


async def embed_text_batch(texts: List[str]) -> List[List[float]]:

    if not texts:
        return []

    # Q: Should we chunk? If texts are too large, we should split.
    # For now, we embed all at once.
    response = await openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return [item.embedding for item in response.data]
