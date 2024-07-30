from datetime import datetime
from pydantic import BaseModel
from typing import Any, List, Optional

from lib.schemas.patient import PatientDetail


class CGMDataUpload(BaseModel):
    file: bytes
    patient_id: str
    device: str
    serial_number: str



class GlucoseReportResponse(BaseModel):
    patient_detail: PatientDetail
    overall_stats: Any
    day_wise_stats: Any
    week_wise_stats: Any
