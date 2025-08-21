from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/{patient_id}/uploads",
    tags=["Care Provider - Patients Uploads"],
)

from .create import *
