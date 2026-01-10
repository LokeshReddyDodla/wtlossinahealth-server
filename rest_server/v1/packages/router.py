from fastapi import APIRouter

router = APIRouter(prefix="/packages", tags=["V1 - Packages"])

from .list import *

