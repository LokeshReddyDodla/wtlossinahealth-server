from sqlalchemy.orm import Session
from lib.models.patient_token_usage_log import PatientTokenUsageLog
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID


class PatientTokenUsageLogger:
    @staticmethod
    async def log_usage(
        postgres_session: AsyncSession,
        patient_id: UUID,
        tokens_used: int,
        model_used: str,
        api_type: str,
        api_endpoint: str,
    ) -> None:
        log_entry = PatientTokenUsageLog(
            patient_id=patient_id,
            tokens_used=tokens_used,
            model_used=model_used,
            api_type=api_type,
            api_endpoint=api_endpoint,
        )
        postgres_session.add(log_entry)
        await postgres_session.commit()
