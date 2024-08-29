from fastapi import APIRouter

router = APIRouter(prefix="/patient/vitals", tags=["Vitals"])

from .read import *
from .upload import *
