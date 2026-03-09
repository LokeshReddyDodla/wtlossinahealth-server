from fastapi import APIRouter

router = APIRouter(prefix="/patients", tags=["V1 - Patients"])

from .list import *
from .read import *
from .data_availability import *
from .patient_daily_overview import *
from .exports import *
