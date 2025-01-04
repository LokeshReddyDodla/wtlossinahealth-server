from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from lib.schemas.glucose_stats import (GlucoseDailyReport,
                                       GlucoseOverallReport,
                                       GlucoseWeeklyReport)
from lib.schemas.patient import Patient
from rest_server.response_models import SuccessResponse


class CGMDataUpload(BaseModel):
    file: bytes
    patient_id: str
    device: str
    serial_number: str
