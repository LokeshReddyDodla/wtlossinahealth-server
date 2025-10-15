from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/{patient_id}/smbg",
    tags=["Care Provider - Patient SMBG"],
)


from .read import *
