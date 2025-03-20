from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from lib.core.types import OpenAIModelLiteral


class TokenUsageLogBase(BaseModel):
    user_id: UUID
    user_type: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: Optional[int]
    cost: int
    model_used: OpenAIModelLiteral
    api_type: str  # e.g., 'openai', 'third_party'
    api_endpoint: str  # e.g., 'gpt-4o', 'image_classification'
    created_at: datetime

    class Config:
        from_attributes = True
        protected_namespaces = ()


class TokenUsageLog(TokenUsageLogBase):
    id: UUID

    class Config:
        from_attributes = True
