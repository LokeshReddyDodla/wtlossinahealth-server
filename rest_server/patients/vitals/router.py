from fastapi import APIRouter

router = APIRouter(prefix="/patient/vitals", tags=["Patient - Vitals"])

from .read import *
from .upload import *
