from fastapi import APIRouter

router = APIRouter(prefix="/patients", tags=["Care Provider - Patients"])

from .read import *
from .update import *
