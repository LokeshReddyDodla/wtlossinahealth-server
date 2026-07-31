from fastapi import APIRouter

router = APIRouter(prefix="/ai-features", tags=["Admin - AI Features"])

from .read import *
from .update import *
