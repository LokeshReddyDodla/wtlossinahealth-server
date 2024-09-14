from sqlalchemy import exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from lib.models.patient import Patient
from lib.models.patient_care_provider import PatientCareProvider
from lib.models.care_provider import CareProvider
from lib.models.patient_connected_app import PatientConnectedApp


class PatientService:
    def __init__(self, postgres_session: AsyncSession):
        self.postgres_session = postgres_session

    async def fetch_patient(
        self, patient_id: str, detailed: bool = False
    ) -> Patient:
        try:
            stmt = select(Patient).where(Patient.patient_id == patient_id)

            if detailed:
                stmt = stmt.options(
                    selectinload(Patient.daily_activity),
                    selectinload(Patient.food_allergies),
                    selectinload(Patient.drug_allergies),
                    selectinload(Patient.diet_preferences),
                    selectinload(Patient.alcohol_consumption),
                    selectinload(Patient.smoking_habit),
                    selectinload(Patient.meal_timings),
                    selectinload(Patient.cuisine_preferences),
                    selectinload(Patient.sleep_habit),
                    selectinload(Patient.diabetic_history),
                    selectinload(Patient.family_diabetic_histories),
                    selectinload(Patient.medical_histories),
                    selectinload(Patient.current_medication),
                    selectinload(Patient.permissions),
                    selectinload(Patient.vitals),
                    selectinload(Patient.smbgs),
                    selectinload(Patient.connected_apps).selectinload(
                        PatientConnectedApp.libreview
                    ),
                    selectinload(Patient.connected_apps).selectinload(
                        PatientConnectedApp.other_app
                    ),
                    selectinload(Patient.fitness_sync),
                    selectinload(Patient.token_usage_logs),
                    selectinload(Patient.care_providers)
                    .selectinload(PatientCareProvider.care_provider)
                    .selectinload(CareProvider.health_facility),
                    selectinload(Patient.health_facility),
                )

            result = await self.postgres_session.execute(stmt)
            patient = result.scalars().first()

            if not patient:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Patient not found.",
                )

            return patient

        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def check_patient_exists(self, patient_id: str) -> bool:
        try:
            stmt = select(exists().where(Patient.patient_id == patient_id))
            result = await self.postgres_session.execute(stmt)
            (exists_result,) = result.scalars()

            if not exists_result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Patient not found.",
                )

            return True
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )
