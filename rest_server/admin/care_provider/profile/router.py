from fastapi import APIRouter

router = APIRouter(
    prefix="/admin/care-providers/profile",
    tags=["Admin - Care Provider"],
)

from .create import *
