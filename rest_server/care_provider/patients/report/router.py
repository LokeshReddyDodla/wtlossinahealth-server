from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/{patient_id}/reports",
    tags=["Care Provider - Patient Reports"],
)

from .read import *
