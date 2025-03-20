from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.utils.http_exceptions import raise_http_exception


async def get_current_patient(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    user_role: tuple = Depends(get_current_user),
):
    try:
        user_id, role = user_role
        if role != ProfileTypeEnum.PATIENT.value:
            raise_http_exception(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message="Access denied. Token is invalid or expired.",
            )

        result = await session.execute(
            select(Patient).where(Patient.patient_id == user_id)
        )
        patient = result.scalars().first()
        if not patient:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message=f"Patient with ID '{user_id}' not found.",
            )
        return patient
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="An unexpected error occurred while retrieving the current patient.",
            detail=str(e),
        )
