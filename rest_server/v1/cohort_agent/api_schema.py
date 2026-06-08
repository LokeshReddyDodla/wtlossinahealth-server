from typing import Any

from pydantic import BaseModel, Field


class CohortQueryRequest(BaseModel):
    message: str = Field(..., description="The care provider's free-text question")
    # Opaque agent conversation state from a previous response, for multi-turn.
    history: list[Any] = Field(default_factory=list)


class CohortQueryResponse(BaseModel):
    answer: str
    history: list[Any]
