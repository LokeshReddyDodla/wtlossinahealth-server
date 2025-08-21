from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/{patient_id}/report",
    tags=["Care Provider - Patient Reports"],
)

from .read import *
