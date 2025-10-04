from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel, Field
import instructor
from openai import AsyncOpenAI

from .models import SearchIntent
from .constants import SYSTEM_PROMPT_TEMPLATE


class IntentExtractor:
    def __init__(self, openai_client: AsyncOpenAI):
        self.client = instructor.from_openai(openai_client)

    async def extract(self, query: str) -> SearchIntent:
        current_date = datetime.now(timezone.utc).isoformat()
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            current_date=current_date
        )

        try:
            intent = await self.client.chat.completions.create(
                model="gpt-4o",
                response_model=SearchIntent,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                max_retries=2,
            )
            return intent
        except Exception as e:
            print(f"Critical LLM failure: {e}")
            return SearchIntent(semantic_query=query)
