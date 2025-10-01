from openai import AsyncOpenAI

openai_client = AsyncOpenAI()


async def embed_text(text: str) -> list[float]:
    response = await openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding
