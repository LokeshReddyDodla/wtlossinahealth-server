from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from lib.schemas.patient import CorePatientProfile
from rest_server.response_models import SuccessResponse


class CGMReportListItem(BaseModel):
    """Response model for a single CGM report in a list"""
    report_id: Optional[str] = Field(None, description="Report ID")
    start_date: datetime = Field(..., description="Report start date")
    end_date: datetime = Field(..., description="Report end date")


class CGMReportListResponse(BaseModel):
    """Response model for list of CGM reports"""
    reports: List[CGMReportListItem] = Field(..., description="List of CGM reports")
    total: int = Field(..., description="Total number of reports")


class CGMReportDetailResponse(BaseModel):
    """Response model for a detailed CGM report with patient info"""
    patient_info: CorePatientProfile = Field(..., description="Patient profile information")
    report: Dict[str, Any] = Field(..., description="CGM report data")


# Typed Success Responses
ListCGMReportsResponse = SuccessResponse[CGMReportListResponse]
GetCGMReportResponse = SuccessResponse[CGMReportDetailResponse]
