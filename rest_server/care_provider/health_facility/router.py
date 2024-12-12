from fastapi import APIRouter

router = APIRouter(prefix="/health-facility", tags=["Care Provider"])

from .read import *
