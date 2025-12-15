from datetime import datetime, timedelta, timezone
from typing import List
from sqlalchemy import distinct, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import status

from lib.core.constants import ProfileTypeEnum
from lib.models.user_activity_log import UserActivityLog
from lib.models.patient import Patient
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session


class ActivePatientService:
    @with_postgres_session
    async def get_active_patients(
        self, days: int, *, postgres_session: AsyncSession
    ) -> List[str]:
        try:
            if days < 0:
                raise ValueError("days must be non-negative")

            # Calculate the cutoff datetime (days ago from now)
            cutoff_datetime = datetime.now(timezone.utc) - timedelta(days=days)

            stmt = (
                select(distinct(UserActivityLog.user_id))
                .select_from(UserActivityLog)
                .join(
                    Patient, Patient.patient_id == UserActivityLog.user_id
                )
                .where(
                    UserActivityLog.profile_type
                    == ProfileTypeEnum.PATIENT.value
                )
                .where(UserActivityLog.active_at >= cutoff_datetime)
            )

            result = await postgres_session.execute(stmt)
            patient_ids = result.scalars().all()
            return [str(pid) for pid in patient_ids]

        except ValueError as e:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid parameter",
                detail=str(e),
            )
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch active patients",
                detail=str(e),
            )

