from datetime import datetime
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from lib.schemas.glucose import GlucoseLevelStats
from lib.schemas.patient import PatientDetail


class CGMDataUpload(BaseModel):
    file: bytes
    patient_id: str
    device: str
    serial_number: str


class GlucoseReportResponse(BaseModel):
    patient_detail: PatientDetail
    overall_stats: Dict[str, GlucoseLevelStats]
    day_wise_stats: Dict[str, GlucoseLevelStats]
    week_wise_stats: Dict[str, GlucoseLevelStats]
