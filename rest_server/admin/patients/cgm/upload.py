from datetime import datetime
from io import StringIO
from typing import Union

import pandas as pd
from fastapi import (APIRouter, Depends, File, HTTPException, Request, status,
                     UploadFile)
from lib.dependencies.service_dependencies import get_cgm_service
from lib.services.cgm_upload_service import CGMUploadService
from lib.utils.http_exceptions import raise_http_exception
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session, selectinload

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.database import get_postgres_session
from lib.models.admin import Admin
from lib.models.patient import Patient
from lib.models.patient_connected_app import PatientConnectedApp
from rest_server.response_models import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/admin/patient")


@router.post("/cgm/upload", tags=["Admin Patient"])
async def admin_upload_cgm_data(
    request: Request,
    patient_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_postgres_session),
    cgm_upload_service: CGMUploadService = Depends(get_cgm_service),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        await cgm_upload_service.parse_and_upload_cgm_data(
            patient_id=str(patient_id),
            file_contents=await file.read(),
        )
       
        return SuccessResponse(
            message="CGM data uploaded and stored successfully."
        )

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
