from fastapi import APIRouter

router = APIRouter(prefix="/consultations", tags=["Consultations"])

from .create import *  # noqa: E402,F401,F403
from .read import *  # noqa: E402,F401,F403
