from fastapi import APIRouter

router = APIRouter(
    prefix="/health-facility", tags=["Care Provider - Health Facility"]
)

from .read import *
