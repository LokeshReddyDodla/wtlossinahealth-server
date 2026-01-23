from fastapi import APIRouter

router = APIRouter(prefix="/patients", tags=["V1 - Patients"])

from .list import *
from .read import *

