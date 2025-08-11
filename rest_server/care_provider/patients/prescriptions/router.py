from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/prescriptions",
    tags=["Care Provider - Patients Prescriptions"],
)


from .read import *
