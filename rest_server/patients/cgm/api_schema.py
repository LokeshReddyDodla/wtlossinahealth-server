from datetime import datetime
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from lib.schemas.glucose_stats import (
    GlucoseDailyReport,
    GlucoseOverallReport,
    GlucoseWeeklyReport,
)
from lib.schemas.patient import CompletePatientProfile
from rest_server.response_models import SuccessResponse


class CGMDataUpload(BaseModel):
    file: bytes
    patient_id: str
    device: str
    serial_number: str


class CompleteGlucoseReport(BaseModel):
    patient_detail: CompletePatientProfile
    overall_stats: GlucoseOverallReport
    day_wise_stats: GlucoseDailyReport
    week_wise_stats: GlucoseWeeklyReport


GlucoseReportResponse = SuccessResponse[CompleteGlucoseReport]
