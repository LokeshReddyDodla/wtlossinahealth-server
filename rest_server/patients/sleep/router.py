from fastapi import APIRouter

router = APIRouter(prefix="/patient/sleep", tags=["Patient - Sleep"])

from .read import *
