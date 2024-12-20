from fastapi import APIRouter

router = APIRouter(prefix="/patients", tags=["Care Provider - Patients"])

from .delete import *
from .read import *
from .update import *
