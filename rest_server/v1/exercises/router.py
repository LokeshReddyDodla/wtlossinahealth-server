from fastapi import APIRouter

router = APIRouter(prefix="/exercises", tags=["Exercises"])

from .read import *  # noqa: E402,F401,F403
