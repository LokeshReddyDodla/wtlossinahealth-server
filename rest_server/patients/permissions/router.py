from fastapi import APIRouter

router = APIRouter(
    prefix="/patient/permissions", tags=["Patient - Permissions"]
)

from .read import *
from .update import *
