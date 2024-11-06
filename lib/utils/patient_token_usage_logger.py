from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from lib.core.postgres_store import PostgresStore
from lib.core.types import OpenAIModelLiteral
from lib.models.patient_token_usage_log import PatientTokenUsageLog


class PatientTokenUsageLogger:
    @staticmethod
    async def log_usage(
        patient_id: UUID,
        tokens_used: int,
        model_used: OpenAIModelLiteral,
        api_type: str,
        api_endpoint: str,
    ) -> None:
        async with PostgresStore().get_session() as session:
            log_entry = PatientTokenUsageLog(
                patient_id=patient_id,
                tokens_used=tokens_used,
                model_used=model_used,
                api_type=api_type,
                api_endpoint=api_endpoint,
            )
            session.add(log_entry)
            await session.commit()
