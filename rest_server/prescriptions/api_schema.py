from typing import Optional

from pydantic import Field
from pydantic import BaseModel
from typing import List, Dict, Optional, Union

from rest_server.response_models import SuccessResponse


class Medicine(BaseModel):
    name: str
    dosage: str
    frequency: str
    duration: str

class PrescriptionData(BaseModel):
    prescription_valid: bool
    doctor_name: Optional[str]
    patient_name: Optional[str]
    prescription_date: Optional[str]
    medicines: Optional[List[Medicine]]

class PrescriptionAnalysisResponse(BaseModel):
    data: PrescriptionData

