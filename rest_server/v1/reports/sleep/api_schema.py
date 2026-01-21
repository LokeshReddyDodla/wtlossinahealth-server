from datetime import date, datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from rest_server.response_models import SuccessResponse


class SleepReportResponse(BaseModel):
    """Response model for a single sleep report"""
    patient_id: str = Field(..., description="Patient ID")
    start_date: datetime = Field(..., description="Report start date")
    end_date: datetime = Field(..., description="Report end date")
    report_type: str = Field(..., description="Report type (daily, weekly, monthly, custom)")
    data: Dict[str, Any] = Field(..., description="Report data")


class SleepReportListResponse(BaseModel):
    """Response model for list of sleep reports"""
    reports: List[SleepReportResponse] = Field(..., description="List of sleep reports")
    total: int = Field(..., description="Total number of reports")


# Typed Success Responses
ListSleepReportsResponse = SuccessResponse[SleepReportListResponse]
GetSleepReportResponse = SuccessResponse[SleepReportResponse]
