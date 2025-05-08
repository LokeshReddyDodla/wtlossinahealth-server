from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/uploads", tags=["Care Provider - Patients Uploads"]
)

from .create import *
