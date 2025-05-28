from typing import List

from lib.schemas.care_provider import CareProvider
from lib.schemas.package import Package
from lib.schemas.patient import Patient


class HealthFacilityPackages(Package):
    care_providers: List[CareProvider] = []


class HealthFacilityCareProviders(CareProvider):
    patients: List[Patient] = []
    packages: List[Package] = []
