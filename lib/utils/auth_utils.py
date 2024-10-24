from fastapi import HTTPException
from sqlalchemy import select

from lib.core.constants import ProfileType
from lib.models.care_provider import CareProvider
from lib.models.patient import Patient


class AuthUtils:
    def __init__(self, postgres_session):
        self.postgres_session = postgres_session

    async def get_or_create_user(self, phone_number: str, role: str):
        if role == ProfileType.PATIENT.value:
            result = await self.postgres_session.execute(
                select(Patient).where(Patient.phone_number == phone_number)
            )

            user = result.scalars().first()
            if not user:
                user = Patient(phone_number=phone_number)
                self.postgres_session.add(user)
                await self.postgres_session.commit()
                await self.postgres_session.refresh(user)

            user_id = str(user.patient_id)

        elif role == ProfileType.CARE_PROVIDER.value:
            result = await self.postgres_session.execute(
                select(CareProvider).where(
                    CareProvider.phone_number == phone_number
                )
            )
            user = result.scalars().first()
            if not user:
                raise HTTPException(
                    status_code=400, detail="Care Provider not found"
                )
            user_id = str(user.care_provider_id)
        else:
            raise HTTPException(status_code=400, detail="Invalid role")
        return user, user_id
