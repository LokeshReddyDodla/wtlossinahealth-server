from fastapi import APIRouter

router = APIRouter(prefix="/health-query-agent", tags=["V1 - Health Query Agent"])

from .query import *
from .history import *
from .reset import *
