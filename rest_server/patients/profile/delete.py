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

from lib.services.chat_service import ChatService
from lib.services.patient_profile_service import PatientService
from rest_server.response_models import SuccessResponse, ErrorResponse
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
        service = PatientService(session)
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
