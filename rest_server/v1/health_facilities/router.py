from fastapi import APIRouter

router = APIRouter(prefix="/health_facilities", tags=["V1 - Health Facilities"])

from .list import *

