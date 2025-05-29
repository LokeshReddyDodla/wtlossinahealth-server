from fastapi import APIRouter

router = APIRouter(
    prefix="/package-assignment", tags=["Care Provider - Package Assignment"]
)

from .create import *
