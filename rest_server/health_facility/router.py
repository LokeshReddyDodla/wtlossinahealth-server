from fastapi import APIRouter

router = APIRouter(prefix="/health-facility", tags=["Health Facility"])

from .read import *
from .update import *
