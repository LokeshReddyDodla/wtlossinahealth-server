from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/meals", tags=["Care Provider - Patients Meals"]
)


from .analyze import *
from .read import *
from .delete import *
