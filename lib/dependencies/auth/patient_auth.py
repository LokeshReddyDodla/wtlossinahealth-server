from fastapi import Depends, HTTPException, Request
from lib.dependencies.auth.base import get_current_user
from sqlalchemy.future import select
from lib.models.patient import Patient


async def get_current_patient(
    request: Request,
    user_role: tuple = Depends(get_current_user),
):
    user_id, role = user_role
    if role != "patient":
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    async with request.state.context.postgres_store.get_session() as session:
        result = await session.execute(
            select(Patient).where(Patient.patient_id == user_id)
        ) 
        patient = result.scalars().first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
    return patient
