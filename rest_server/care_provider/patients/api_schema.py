from typing import List

from pydantic import BaseModel

from lib.schemas.care_provider import CareProvider
from lib.schemas.patient import Patient
from rest_server.response_models import SuccessResponse


class CareProviderPatients(Patient):
    care_providers: List[CareProvider] = []
