from fastapi import APIRouter

router = APIRouter(prefix="/patients/cgm", tags=["Care Provider - Patients CGM"])


from .read import *
