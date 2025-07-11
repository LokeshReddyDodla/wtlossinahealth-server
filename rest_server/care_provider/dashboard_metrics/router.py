from fastapi import APIRouter

router = APIRouter(
    prefix="/dashboard/metrics", tags=["Care Provider - Dashboard Metrics"]
)

from .read import *
