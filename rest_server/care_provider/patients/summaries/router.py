from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/{patient_id}/summaries",
    tags=["Care Provider - Patient Summaries"],
)

from .read import *

