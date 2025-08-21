from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/{patient_id}/fitness",
    tags=["Care Provider - Patients Fitness"],
)

from .read import *
