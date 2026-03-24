from fastapi import APIRouter

router = APIRouter(prefix="/health-query-agent", tags=["V1 - Health Query Agent"])

from .query import *
from .query_v3 import *
from .feedback import *
from .history import *
from .history_v3 import *
from .reset import *
from .reset_v3 import *
from .admin_config import *
