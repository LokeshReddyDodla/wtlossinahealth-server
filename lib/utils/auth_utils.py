from fastapi import HTTPException, status
from sqlalchemy import select

from lib.core.constants import ProfileType
from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.utils.http_exceptions import raise_http_exception


class AuthUtils:
    def __init__(self, postgres_session):
        self.postgres_session = postgres_session

    async def get_or_create_user(self, phone_number: str, role: str):
        try:
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
                    raise_http_exception(
                        status_code=status.HTTP_404_NOT_FOUND,
                        message=f"Care Provider with phone number '{phone_number}' not found.",
                    )

                user_id = str(user.care_provider_id)

            else:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Invalid role provided. Must be 'PATIENT' or 'CARE_PROVIDER'.",
                )
            return user, user_id

        except Exception as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="An unexpected error occurred while processing user authentication.",
                detail=str(e),
            )
