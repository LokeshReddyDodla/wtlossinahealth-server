from typing import List
from lib.schemas.patient_connected_app import (
    PatientLibreView,
    PatientOtherApp,
    PatientConnectedApp,
)
from rest_server.response_models import SuccessResponse


AddLibreViewResponse = SuccessResponse[PatientLibreView]
AddOtherAppResponse = SuccessResponse[PatientOtherApp]
GetPatientConnectedAppsResponse = SuccessResponse[List[PatientConnectedApp]]
