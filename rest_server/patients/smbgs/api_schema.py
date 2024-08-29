from typing import List
from lib.schemas.patient_smbg import PatientSMBG
from rest_server.response_models import SuccessResponse


PatientSmbgsResponse = SuccessResponse[List[PatientSMBG]]

PatientSmbgUploadResponse = SuccessResponse[PatientSMBG]
