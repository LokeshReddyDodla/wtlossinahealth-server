from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.models.patient_care_provider import (
    PatientCareProvider as PatientCareProviderModel,
)
from fastapi import HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.exc import SQLAlchemyError

from typing import List, Optional, Union
from sqlalchemy.future import select
from lib.schemas.patient_care_provider import (
    PatientCareProvider as PatientCareProviderSchema,
    PatientCareProviderCreate,
)
from sqlalchemy.exc import IntegrityError
from rest_server.patients.care_provider.api_schema import (
    PatientCareProviderResponse,
)
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.post("", response_model=PatientCareProviderResponse)
async def create_patient_care_provider(
    request: Request, patient_care_provider: PatientCareProviderCreate
) -> Union[PatientCareProviderResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            new_patient_care_provider = PatientCareProviderModel(
                **patient_care_provider.dict()
            )
            session.add(new_patient_care_provider)

            # Fetch the patient
            patient_stmt = select(Patient).filter_by(
                patient_id=patient_care_provider.patient_id
            )
            patient_result = await session.execute(patient_stmt)
            patient = patient_result.scalars().first()
            if not patient:
                raise HTTPException(
                    status_code=404, detail="Patient not found."
                )

            # Fetch the care provider
            care_provider_stmt = select(CareProvider).filter_by(
                care_provider_id=patient_care_provider.care_provider_id
            )
            care_provider_result = await session.execute(care_provider_stmt)
            care_provider = care_provider_result.scalars().first()

            if not care_provider:
                raise HTTPException(
                    status_code=404, detail="Care provider not found."
                )

            if patient.health_facility_id is None:
                patient.health_facility_id = care_provider.health_facility_id

            await session.commit()
            await session.refresh(new_patient_care_provider)
            await session.refresh(patient)

            return PatientCareProviderResponse(
                message="Patient care provider created successfully",
                data=PatientCareProviderSchema.from_orm(
                    new_patient_care_provider
                ),
            )
        except IntegrityError:
            raise HTTPException(
                status_code=400,
                detail="Patient care provider association already exists.",
            )
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
