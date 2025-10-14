from datetime import datetime, timezone
import json
from typing import Optional, List
from pydantic import BaseModel, Field
import instructor
from openai import AsyncOpenAI

from .models import SearchIntent
from .constants import (
    SYSTEM_PROMPT_CONTEXTUAL_TEMPLATE,
    SYSTEM_PROMPT_TEMPLATE,
)


class IntentExtractor:
    def __init__(self, openai_client: AsyncOpenAI):
        self.client = instructor.from_openai(openai_client)

    async def extract(
        self,
        query: str,
        context_intents: Optional[List[SearchIntent]] = None,
    ) -> SearchIntent:
        current_date = datetime.now(timezone.utc).isoformat()

        if context_intents:
            # Serialize context for the LLM
            context_json = json.dumps(
                [i.model_dump() for i in context_intents[-3:]], indent=2
            )

            # Use your normal system prompt + the contextual one
            system_prompt = (
                SYSTEM_PROMPT_TEMPLATE.format(current_date=current_date)
                + "\n\n"
                + SYSTEM_PROMPT_CONTEXTUAL_TEMPLATE.format(
                    context_json=context_json
                )
            )
        else:
            # No context → normal behavior
            system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                current_date=current_date
            )

        try:
            intent = await self.client.chat.completions.create(
                model="gpt-4o",
                temperature=0,
                top_p=1,
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
