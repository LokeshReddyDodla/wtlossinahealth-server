from typing import List, Optional

from pydantic import BaseModel

from rest_server.response_models import SuccessResponse


class Medicine(BaseModel):
    name: str
    dosage: str
    frequency: str
    duration: str
    purpose: str
    effects: str

class PrescriptionData(BaseModel):
    prescription_valid: bool
    doctor_name: Optional[str]
    patient_name: Optional[str]
    prescription_date: Optional[str]
    medicines: Optional[List[Medicine]]

class PrescriptionAnalysisResponse(SuccessResponse):
    data: PrescriptionData

