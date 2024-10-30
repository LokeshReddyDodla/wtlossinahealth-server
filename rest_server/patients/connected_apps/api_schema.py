from typing import List

from lib.schemas.patient_connected_app import (PatientConnectedApp,
                                               PatientLibreView,
                                               PatientOtherApp)
from rest_server.response_models import SuccessResponse

UpdateLibreViewResponse = SuccessResponse[PatientLibreView]
AddOtherAppResponse = SuccessResponse[PatientOtherApp]
GetPatientConnectedAppsResponse = SuccessResponse[PatientConnectedApp]
