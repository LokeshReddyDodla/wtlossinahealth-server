from fastapi import APIRouter

router = APIRouter(prefix="/health-query-agent", tags=["V1 - Health Query Agent"])

from .query_v3 import *
from .feedback import *
from .history_v3 import *
from .reset_v3 import *
from .admin_config import *
from .proactive_scan import *
from .proactive_insights import *
from .patient_memories import *
from .provider_panel import *
