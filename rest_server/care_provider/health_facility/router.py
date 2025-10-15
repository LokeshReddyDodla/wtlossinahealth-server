from fastapi import APIRouter

router = APIRouter(
    prefix="/health-facilities",
    tags=["Care Provider - Health Facility"],
)

from .read import *
