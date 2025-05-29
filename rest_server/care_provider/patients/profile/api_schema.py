from typing import List, Optional

from pydantic import BaseModel

from lib.schemas.care_provider import CareProvider
from lib.schemas.health_facility import HealthFacility
from lib.schemas.patient import Patient
from lib.schemas.patient_package_assignment import (
    PatientPackageAssignment,
    PatientPackageAssignmentWithDetail,
)
from rest_server.response_models import SuccessResponse


class CareProviderPatients(Patient):
    care_providers: List[CareProvider] = []
    health_facility: Optional[HealthFacility] = None
    current_package: Optional[PatientPackageAssignmentWithDetail] = None
