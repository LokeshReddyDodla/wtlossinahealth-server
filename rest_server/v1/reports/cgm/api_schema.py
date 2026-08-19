from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from lib.schemas.cgm_stats import ReportMetadata
from lib.schemas.patient import CorePatientProfile
from rest_server.response_models import SuccessResponse


class SymptomLogItem(BaseModel):
    name: str = Field(..., description="Symptom name or custom label")
    severity: int = Field(..., description="Severity 1-5")


class SymptomLog(BaseModel):
    recorded_at: datetime = Field(..., description="Patient-local time symptoms were felt")
    notes: Optional[str] = Field(None, description="Free-text note")
    items: List[SymptomLogItem] = Field(..., description="Symptoms in this entry")


class CGMReportListItem(BaseModel):
    """Response model for a single CGM report in a list"""

    report_id: Optional[str] = Field(None, description="Report ID")
    metadata: Optional[ReportMetadata] = Field(..., description="Report metadata")


class CGMReportListResponse(BaseModel):
    """Response model for list of CGM reports"""

    reports: List[CGMReportListItem] = Field(..., description="List of CGM reports")
    total: int = Field(..., description="Total number of reports")


class CGMReportDetailResponse(BaseModel):
    """Response model for a detailed CGM report with patient info"""

    patient_info: CorePatientProfile = Field(
        ..., description="Patient profile information"
    )
    report: Dict[str, Any] = Field(..., description="CGM report data")
    symptoms: List[SymptomLog] = Field(
        default_factory=list, description="Symptoms logged within the report window"
    )


# Typed Success Responses
ListCGMReportsResponse = SuccessResponse[CGMReportListResponse]
GetCGMReportResponse = SuccessResponse[CGMReportDetailResponse]
