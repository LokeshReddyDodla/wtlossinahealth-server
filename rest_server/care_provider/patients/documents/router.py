from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/{patient_id}/documents",
    tags=["Care Provider - Patient Documents"],
)

from .read import *
from .create import *
from .research import *
