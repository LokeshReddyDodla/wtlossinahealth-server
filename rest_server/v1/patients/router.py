from fastapi import APIRouter

router = APIRouter(prefix="/patients", tags=["V1 - Patients"])

from .list import *
from .data_richness import *
from .read import *
from .data_availability import *
from .patient_daily_overview import *
from .exports import *
from .vitals import *
from .checkins import *
from .checkin_history import *
from .smbg import *
