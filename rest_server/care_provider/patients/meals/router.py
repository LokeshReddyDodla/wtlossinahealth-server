from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/meals", tags=["Care Provider - Patients Meals"]
)


from .read import *
