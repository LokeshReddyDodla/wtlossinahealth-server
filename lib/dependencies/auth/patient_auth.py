from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.constants import PROFILE_TYPE_PATIENT
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient


async def get_current_patient(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    user_role: tuple = Depends(get_current_user),
):
    user_id, role = user_role
    if role != PROFILE_TYPE_PATIENT:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    result = await session.execute(
        select(Patient).where(Patient.patient_id == user_id)
    )
    patient = result.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient
