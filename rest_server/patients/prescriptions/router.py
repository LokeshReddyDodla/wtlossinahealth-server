from fastapi import APIRouter

router = APIRouter(prefix="/prescriptions", tags=["Patient - Prescriptions"])

from .analyze_prescription import *
