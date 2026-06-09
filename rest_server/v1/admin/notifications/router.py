from fastapi import APIRouter

router = APIRouter(
    prefix="/admin/notifications",
    tags=["Admin – Notifications"],
)

from .broadcast import *  # noqa: F401,E402,F403
