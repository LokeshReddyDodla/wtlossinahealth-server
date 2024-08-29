from fastapi import APIRouter

router = APIRouter(prefix="/patient/permissions", tags=["Permissions"])

from .read import *
from .update import *
