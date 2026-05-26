from fastapi import APIRouter

router = APIRouter(prefix="/meals", tags=["Meals"])

from .preview import *  # noqa: E402,F401,F403
from .preview_voice import *  # noqa: E402,F401,F403
from .create import *  # noqa: E402,F401,F403
from .read import *  # noqa: E402,F401,F403
from .update import *  # noqa: E402,F401,F403
from .delete import *  # noqa: E402,F401,F403
