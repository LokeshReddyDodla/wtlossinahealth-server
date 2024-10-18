from fastapi import APIRouter

router = APIRouter(prefix="/patient/overview", tags=["Overview"])

from .read import *
