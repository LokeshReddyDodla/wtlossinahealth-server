from fastapi import APIRouter

router = APIRouter(
    prefix="/care-providers",
    tags=["Admin - Care Provider"],
)

from .create import *
