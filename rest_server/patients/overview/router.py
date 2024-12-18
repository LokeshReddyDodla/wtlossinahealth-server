from fastapi import APIRouter

router = APIRouter(prefix="/patient/overview", tags=["Patient - Overview"])

from .read import *
