from fastapi import APIRouter

router = APIRouter(prefix="/overview", tags=["Patient - Overview"])

from .read import *
