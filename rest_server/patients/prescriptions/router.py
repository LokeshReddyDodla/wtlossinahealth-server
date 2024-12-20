from fastapi import APIRouter

router = APIRouter(
    prefix="/patient/prescriptions", tags=["Patient - Prescriptions"]
)

from .analyze_prescription import *
