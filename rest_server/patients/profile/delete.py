from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from lib.models.patient_connected_app import PatientConnectedApp
from lib.services.patient_profile_service import PatientProfileService
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.delete(path="/delete", response_model=SuccessResponse)
async def delete_patient_api(
    request: Request,
    delete_chats: Optional[bool] = True,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    """
    Delete Patient API
    """
    async with request.state.context.postgres_store.get_session() as session:
        service = PatientProfileService(session)
        try:
            await service.delete_patient_profile(
                patient_id=str(current_patient.patient_id), delete_chats=True
            )

            return SuccessResponse(message="Patient deleted successfully.")
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
