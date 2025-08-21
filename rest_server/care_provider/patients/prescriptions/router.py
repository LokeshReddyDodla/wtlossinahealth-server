from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/{patient_id}/prescriptions",
    tags=["Care Provider - Patients Prescriptions"],
)

from .read import *
