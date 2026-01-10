from datetime import date as datetime_date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from rest_server.response_models import SuccessResponse


class TokenUsageDayResponse(BaseModel):
    date: datetime_date = Field(..., description="Date of usage")
    total_input_tokens: int = Field(..., description="Total input tokens for the date")
    total_output_tokens: int = Field(..., description="Total output tokens for the date")
    total_cached_input_tokens: Optional[int] = Field(
        None, description="Total cached input tokens for the date"
    )
    total_cost: Decimal = Field(..., description="Total cost for the date")


class TokenUsageListResponse(BaseModel):
    usage: List[TokenUsageDayResponse] = Field(
        ..., description="List of token usage grouped by date"
    )
    total: int = Field(..., description="Total number of days with usage")


# Typed Success Responses
ListTokenUsageResponse = SuccessResponse[TokenUsageListResponse]
