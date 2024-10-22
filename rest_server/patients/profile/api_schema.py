from lib.schemas.patient import (CompletePatientProfile, CorePatientProfile,
                                 Patient)
from rest_server.response_models import SuccessResponse

PatientCompleteProfileResponse = SuccessResponse[CompletePatientProfile]

PatientProfileResponse = SuccessResponse[CorePatientProfile]
