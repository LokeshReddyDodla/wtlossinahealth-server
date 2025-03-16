from typing import Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.types import OpenAIModelLiteral
from lib.models.patient_token_usage_log import PatientTokenUsageLog

PRICING = {
    "gpt-4o-mini": {
        "text": 0.002,  # $ per token for text
    },
    "gpt-4o": {
        "image": 0.01,  # $ per token for image
    },
}


class PatientTokenUsageService:
    def __init__(self, postgres_session: AsyncSession):
        self.postgres_session = postgres_session

    async def get_usage_summary(
        self, patient_id: str
    ) -> Dict[str, Dict[str, float]]:
        try:
            stmt = (
                select(
                    PatientTokenUsageLog.model_used,
                    func.sum(PatientTokenUsageLog.tokens_used).label(
                        "total_tokens"
                    ),
                )
                .where(PatientTokenUsageLog.patient_id == patient_id)
                .group_by(PatientTokenUsageLog.model_used)
            )
            result = await self.postgres_session.execute(stmt)
            usage = result.all()

            summary = {}
            for model_used, total_tokens in usage:
                if model_used in PRICING:
                    # Determine whether it's text or image based on the model used
                    if model_used == "gpt-4o-mini":
                        model_type = "text"
                    elif model_used == "gpt-4o":
                        model_type = "image"
                    else:
                        continue

                    price_per_token = PRICING[model_used][model_type]
                    total_cost = total_tokens * price_per_token

                    summary[model_type] = {
                        "model_used": model_used,
                        "total_tokens": total_tokens,
                        "total_cost": round(total_cost, 4),
                    }

            return summary

        except Exception as e:
            raise ValueError(f"Failed to calculate token usage: {e}")

    async def log_usage(
        self,
        patient_id: str,
        model_used: OpenAIModelLiteral,
        tokens_used: int,
        api_type: str,
        api_endpoint: str,
    ) -> None:
        try:
            log = PatientTokenUsageLog(
                patient_id=patient_id,
                model_used=model_used,
                tokens_used=tokens_used,
                api_type=api_type,
                api_endpoint=api_endpoint,
            )
            self.postgres_session.add(log)
            await self.postgres_session.commit()

        except Exception as e:
            await self.postgres_session.rollback()
            raise ValueError(f"Failed to log token usage: {e}")
