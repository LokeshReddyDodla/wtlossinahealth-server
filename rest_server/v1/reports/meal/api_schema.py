from datetime import date as datetime_date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from rest_server.response_models import SuccessResponse


class MealReportResponse(BaseModel):
    """Response model for a single meal report"""
    date: datetime_date = Field(..., description="Report date")
    patient_id: str = Field(..., description="Patient ID")
    report_type: str = Field(..., description="Report type (daily)")
    data: Dict[str, Any] = Field(..., description="Report data")


class MealReportListResponse(BaseModel):
    """Response model for list of meal reports"""
    reports: List[MealReportResponse] = Field(..., description="List of meal reports")
    total: int = Field(..., description="Total number of reports")


class MealReportJob(BaseModel):
    patient_id: str
    job_id: Optional[str]
    status: str


class SyncMealReportResponse(BaseModel):
    message: str
    report_date: datetime_date
    jobs: List[MealReportJob]



# Typed Success Responses
ListMealReportsResponse = SuccessResponse[MealReportListResponse]
GetMealReportResponse = SuccessResponse[MealReportResponse]
