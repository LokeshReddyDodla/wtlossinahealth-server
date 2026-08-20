from fastapi import APIRouter

router = APIRouter(
    prefix="/admin/ops",
    tags=["Admin – Ops"],
)

from .regenerate import *  # noqa: F401,E402,F403
from .vector_coverage import *  # noqa: F401,E402,F403
from .derived import *  # noqa: F401,E402,F403
