from typing import List
from lib.schemas.care_provider import CareProvider
from lib.schemas.health_facility import HealthFacility
from lib.schemas.package import Package


class PackageByCodeResponse(Package):
    care_providers: List[CareProvider]
    health_facility: HealthFacility
