from typing import List, Optional

from pydantic import BaseModel

from lib.schemas.care_provider import CareProvider
from lib.schemas.health_facility import HealthFacility
from lib.schemas.package import Package
from lib.schemas.patient import Patient
from rest_server.response_models import SuccessResponse


class CareProviderPatients(Patient):
    care_providers: List[CareProvider] = []
    package: Optional[Package] = None
    health_facility: Optional[HealthFacility] = None
