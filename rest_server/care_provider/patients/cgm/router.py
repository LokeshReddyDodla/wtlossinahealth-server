from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/{patient_id}/cgm", tags=["Care Provider - Patients CGM"]
)
from .read import *
