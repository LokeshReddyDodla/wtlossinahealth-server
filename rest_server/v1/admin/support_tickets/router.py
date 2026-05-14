from fastapi import APIRouter

router = APIRouter(
    prefix="/admin/support_tickets",
    tags=["Admin – Support Tickets"],
)

from .read import *  # noqa: F401,E402,F403
from .update import *  # noqa: F401,E402,F403
