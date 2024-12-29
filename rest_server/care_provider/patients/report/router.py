from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/report", tags=["Care Provider - Patients Report"]
)

from .read import *
