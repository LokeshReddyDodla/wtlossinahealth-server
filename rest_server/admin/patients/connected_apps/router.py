from fastapi import APIRouter

router = APIRouter(prefix="/patients/connected-apps", tags=["Admin - Patients Connected Apps"])

from .read import *

