from fastapi import APIRouter

router = APIRouter(prefix="/patient/prescriptions", tags=["Prescriptions"])

from .analyze_prescription import *
