from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/{patient_id}/meals",
    tags=["Care Provider - Patient Meals"],
)


from .analyze import *
from .read import *
from .delete import *
