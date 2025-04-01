from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/fitness", tags=["Care Provider - Patients Fitness"]
)


from .read import *
