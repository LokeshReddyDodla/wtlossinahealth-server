from fastapi import APIRouter

router = APIRouter(
    prefix="/admin/system",
    tags=["Admin – System"],
)

from .pulse import *  # noqa: F401,E402,F403
