from fastapi import APIRouter

router = APIRouter(prefix="/connected-apps", tags=["Admin - Connected Apps"])

from .read import *

