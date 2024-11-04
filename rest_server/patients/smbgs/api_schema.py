from typing import List

from pydantic import BaseModel

from lib.schemas.patient_smbg import PatientSMBG
from rest_server.response_models import SuccessResponse

PatientSmbgsResponse = SuccessResponse[List[PatientSMBG]]


class PatientSmbgUpload(BaseModel):
    smbg_data: PatientSMBG
    ai_response_generated: bool


PatientSmbgUploadResponse = SuccessResponse[PatientSmbgUpload]
