from datetime import date, datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from rest_server.response_models import SuccessResponse


class FitnessReportResponse(BaseModel):
    """Response model for a single fitness report"""
    patient_id: str = Field(..., description="Patient ID")
    report_type: str = Field(..., description="Report type (daily, weekly, monthly, custom)")
    data: Dict[str, Any] = Field(..., description="Report data")


class FitnessReportListResponse(BaseModel):
    """Response model for list of fitness reports"""
    reports: List[FitnessReportResponse] = Field(..., description="List of fitness reports")
    total: int = Field(..., description="Total number of reports")


# Typed Success Responses
ListFitnessReportsResponse = SuccessResponse[FitnessReportListResponse]
GetFitnessReportResponse = SuccessResponse[FitnessReportResponse]
