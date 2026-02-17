from pydantic import BaseModel, Field

from lib.schemas.patient import CorePatientProfile
from lib.schemas.smbg_stats import SMBGReport
from rest_server.response_models import SuccessResponse


class SMBGReportDetailResponse(BaseModel):
    """Response model for a detailed SMBG report with patient info"""

    patient_info: CorePatientProfile = Field(
        ..., description="Patient profile information"
    )
    report: SMBGReport = Field(..., description="SMBG statistics report data")


# Typed Success Responses
GetSMBGReportResponse = SuccessResponse[SMBGReportDetailResponse]
