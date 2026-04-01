
from datetime import datetime
from typing import Optional

from fastapi import Depends, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_patient_vital_service
from lib.models.patient import Patient
from lib.services.patient_vital_service import PatientVitalService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_patient_vitals(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    start_date: Optional[datetime] = Query(None, description="Filter: time >= (ISO 8601)"),
    end_date: Optional[datetime] = Query(None, description="Filter: time <= (ISO 8601)"),
    patient_vital_service: PatientVitalService = Depends(get_patient_vital_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        vitals, total = await patient_vital_service.get_patient_vitals(
            str(current_patient.patient_id),
            limit=limit, offset=offset,
            start_date=start_date, end_date=end_date,
        )
        return SuccessResponse(
            message=f"{len(vitals)} vitals fetched.",
            data={"vitals": vitals, "total": total, "limit": limit, "offset": offset},
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
