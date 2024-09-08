from lib.schemas.health_facility import HealthFacility
from lib.schemas.patient import CompletePatientProfile
from rest_server.response_models import SuccessResponse


HealthFacilityResponse = SuccessResponse[HealthFacility]
