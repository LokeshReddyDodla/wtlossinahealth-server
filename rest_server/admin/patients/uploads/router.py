from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/uploads", tags=["Admin - Patients Uploads"]
)

from .create import *
