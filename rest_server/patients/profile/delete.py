from sqlalchemy import or_
from lib.models.patient import (
    Patient,
)
from lib.models.patient_connected_app import PatientConnectedApp

from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select

from typing import List, Optional, Union
from sqlalchemy.exc import IntegrityError

from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.delete(
    path="/delete", tags=["Profile"], response_model=SuccessResponse
)
async def delete_patient_api(
    request: Request,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    """
    Delete Patient API
    """
    async with request.state.context.postgres_store.get_session() as session:
        try:
            patient = await session.get(Patient, current_patient.patient_id)
            if not patient:
                raise HTTPException(
                    status_code=404, detail="Patient not found"
                )

            await session.delete(patient)
            await session.commit()

            return SuccessResponse(message="Patient deleted successfully.")
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            await session.rollback()
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
