from fastapi import APIRouter

router = APIRouter(prefix="/patients", tags=["V1 - Patients"])

# Static-path routes must register BEFORE /{patient_id} catch-all
# (FastAPI matches in registration order).
from .list import *
from .data_richness import *
from .facility_transfer import *
from .onboarding import *
from .profile import *
from .read import *
from .data_availability import *
from .patient_daily_overview import *
from .exports import *
from .vitals import *
from .checkins import *
from .checkin_history import *
from .timeline import *
from .day import *
from .progress import *
from .brief import *
from .notifications import *
from .notification_preferences import *
from .smbg import *
from .workouts_voice import *
from .workouts import *
