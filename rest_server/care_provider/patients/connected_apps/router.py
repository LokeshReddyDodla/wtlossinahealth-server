from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/{patient_id}/connected-apps",
    tags=["Patient - Connected Apps"],
)

from .update import *
from .delete import *
