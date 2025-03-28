
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (get_cgm_report_service,
                                                   get_patient_profile_service)
from lib.models.patient import Patient
from lib.schemas.patient import CompletePatientProfile
from lib.services.cgm_report_service import CGMReportService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(path="", response_model=SuccessResponse)
async def get_patient_details(
    request: Request,
    detailed: bool = False,
    include_health_data: bool = False,
    other_related_data: bool = False,
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        result = await patient_profile_service.fetch_patient_profile(
            str(current_patient.patient_id),
            detailed=detailed,
            include_health_data=include_health_data,
            other_related_data=other_related_data,
        )

        cgm_reports = await cgm_report_service.fetch_reports(
            str(current_patient.patient_id)
        )

        return SuccessResponse(
            message="Patient data fetched successfully.",
            data={
                **CompletePatientProfile.from_orm(result).model_dump(),
                "reports": {
                    "cgm": cgm_reports
                },
            },
        )
    except HTTPException as http_exc:
        raise http_exc
    except SQLAlchemyError as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Database Error",
            detail=str(e),
        )
