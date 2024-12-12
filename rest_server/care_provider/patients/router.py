from fastapi import APIRouter

router = APIRouter(prefix="/patients", tags=["Care Provider"])

from .read import *
