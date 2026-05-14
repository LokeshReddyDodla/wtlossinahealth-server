from fastapi import APIRouter

router = APIRouter(prefix="/support_tickets", tags=["Support Tickets"])

from .create import *  # noqa: F401,E402,F403
from .read import *  # noqa: F401,E402,F403
from .update import *  # noqa: F401,E402,F403
