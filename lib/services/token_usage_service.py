from datetime import date
from typing import Optional, Union

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.constants import ProfileTypeEnum
from lib.core.postgres_store import PostgresStore
from lib.core.types import (
    AIModelProviderLiteral,
    GeminiAIModelLiteral,
    OpenAIModelLiteral,
    PerplexityAIModelLiteral,
)
from lib.models.token_usage_log import TokenUsageLog
from lib.utils.postgres_session_decorator import with_postgres_session

PRICING = {
    "gpt-5.1": {
        "input": 1.25 / 1_000_000,
        "cached_input": 0.125 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-5": {
        "input": 1.25 / 1_000_000,
        "cached_input": 0.125 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-5-mini": {
        "input": 0.25 / 1_000_000,
        "cached_input": 0.025 / 1_000_000,
        "output": 2.00 / 1_000_000,
    },
    "gpt-5-pro": {
        "input": 15.00 / 1_000_000,
        "cached_input": None,
        "output": 120.00 / 1_000_000,
    },
    "gpt-4.1": {
        "input": 2.00 / 1_000_000,
        "cached_input": 0.50 / 1_000_000,
        "output": 8.00 / 1_000_000,
    },
    "gpt-4.1-mini": {
        "input": 0.40 / 1_000_000,
        "cached_input": 0.10 / 1_000_000,
        "output": 1.60 / 1_000_000,
    },
    "gpt-4.1-nano": {
        "input": 0.10 / 1_000_000,
        "cached_input": 0.025 / 1_000_000,
        "output": 0.40 / 1_000_000,
    },
    "gpt-4o": {
        "input": 2.50 / 1_000_000,
        "cached_input": 1.25 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "gpt-4o-mini": {
        "input": 0.15 / 1_000_000,
        "cached_input": 0.075 / 1_000_000,
        "output": 0.60 / 1_000_000,
    },
    "o3-mini": {
        "input": 1.10 / 1_000_000,
        "cached_input": 0.55 / 1_000_000,
        "output": 4.40 / 1_000_000,
    },
    "gemini-1.5-flash": {
        "input": 0.075 / 1_000_000,  # $0.075 per 1M input tokens
        "cached_input": 0.01875
        / 1_000_000,  # $0.01875 per 1M cached input tokens
        "output": 0.30 / 1_000_000,  # $0.30 per 1M output tokens
    },
    "gemini-2.0-flash": {
        "input": 0.10 / 1_000_000,  # $0.10 per 1M input tokens
        "cached_input": 0.025 / 1_000_000,  # $0.025 per 1M cached input tokens
        "output": 0.40 / 1_000_000,  # $0.40 per 1M output tokens
    },
    "sonar": {
        "input": 1.00 / 1_000_000,  # $1.00 per 1M input tokens
        "output": 1.00 / 1_000_000,  # $1.00 per 1M output tokens
        "price_per_1000_requests": {
            "high": 12.00 / 1_000,  # $12.00 per 1000 requests
            "medium": 8.00 / 1_000,  # $8.00 per 1000 requests
            "low": 5.00 / 1_000,  # $5.00 per 1000 requests
        },
    },
    "sonar-reasoning": {
        "input": 1.00 / 1_000_000,  # $1.00 per 1M input tokens
        "output": 5.00 / 1_000_000,  # $5.00 per 1M output tokens
        "price_per_1000_requests": {
            "high": 12.00 / 1_000,  # $12.00 per 1000 requests
            "medium": 8.00 / 1_000,  # $8.00 per 1000 requests
            "low": 5.00 / 1_000,  # $5.00 per 1000 requests
        },
    },
}


class TokenUsageService:
    def __init__(
        self,
        postgres_store: PostgresStore,
    ):
        self.postgres_store = postgres_store

    @with_postgres_session
    async def get_usage_summary(
        self,
        user_id: str,
        user_type: ProfileTypeEnum,
        start_date: date,
        end_date: date,
        *,
        postgres_session: AsyncSession,
    ):
        try:
            query = (
                select(
                    func.date(TokenUsageLog.created_at).label("usage_date"),
                    func.sum(TokenUsageLog.input_tokens).label(
                        "total_input_tokens"
                    ),
                    func.sum(TokenUsageLog.output_tokens).label(
                        "total_output_tokens"
                    ),
                    func.sum(TokenUsageLog.cached_input_tokens).label(
                        "total_cached_input_tokens"
                    ),
                    func.sum(TokenUsageLog.cost).label("total_cost"),
                )
                .where(
                    TokenUsageLog.user_id == user_id,
                    TokenUsageLog.user_type == user_type,
                    TokenUsageLog.created_at >= start_date,
                    TokenUsageLog.created_at <= end_date,
                )
                .group_by(func.date(TokenUsageLog.created_at))
                .order_by(func.date(TokenUsageLog.created_at))
            )

            result = await postgres_session.execute(query)
            rows = result.all()

            usage_summary = [
                {
                    "date": row.usage_date,
                    "total_input_tokens": row.total_input_tokens,
                    "total_output_tokens": row.total_output_tokens,
                    "total_cached_input_tokens": row.total_cached_input_tokens,
                    "total_cost": row.total_cost,
                }
                for row in rows
            ]

            return usage_summary

        except Exception as e:
            raise ValueError(f"Failed to calculate token usage summary: {e}")

    @with_postgres_session
    async def log_usage(
        self,
        user_id: str,
        user_type: ProfileTypeEnum,
        model_used: Union[
            OpenAIModelLiteral, GeminiAIModelLiteral, PerplexityAIModelLiteral
        ],
        model_provider: AIModelProviderLiteral,
        input_tokens: int,
        output_tokens: int,
        api_endpoint: str,
        cached_input_tokens: Optional[int] = None,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        try:
            # Calculate the cost
            cost = self.calculate_cost(
                model_used, input_tokens, cached_input_tokens, output_tokens
            )

            log = TokenUsageLog(
                user_id=user_id,
                user_type=user_type,
                model_used=model_used,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens,
                cost=cost,
                model_provider=model_provider,
                api_endpoint=api_endpoint,
            )
            postgres_session.add(log)
            await postgres_session.commit()

        except Exception as e:
            await postgres_session.rollback()
            raise ValueError(f"Failed to log token usage: {e}")

    def calculate_cost(
        self,
        model_used: str,
        input_tokens: int,
        cached_input_tokens: Optional[int],
        output_tokens: int,
    ) -> float:
        """
        Calculate the total cost based on the model used and the number of tokens.
        """
        if model_used not in PRICING:
            raise ValueError(f"Pricing not found for model: {model_used}")

        pricing = PRICING[model_used]

        # Calculate costs for input and output tokens
        input_cost = input_tokens * pricing.get("input", 0)
        output_cost = output_tokens * pricing.get("output", 0)

        # Calculate cost for cached input tokens if the key exists
        cached_input_cost = 0
        if "cached_input" in pricing and cached_input_tokens is not None:
            cached_input_cost = cached_input_tokens * pricing["cached_input"]

        total_cost = input_cost + cached_input_cost + output_cost

        return total_cost
