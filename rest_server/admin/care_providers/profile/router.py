from fastapi import APIRouter

router = APIRouter(
    prefix="/admin/care-providers",
    tags=["Admin - Care Provider"],
)

from .create import *
