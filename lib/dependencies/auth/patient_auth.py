from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from lib.utils.jwt import decode_jwt_token
from sqlalchemy.future import select
from lib.models.patient import Patient

security = HTTPBearer()


async def get_current_patient(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials
    payload = decode_jwt_token(token)
    if payload is None or payload.get("role") != "Patient":
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    patient_id = payload["sub"]
    async with request.state.context.postgres_store.get_session() as session:
        result = await session.execute(
            select(Patient).where(Patient.patient_id == patient_id)
        )
        patient = result.scalars().first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
    return patient
