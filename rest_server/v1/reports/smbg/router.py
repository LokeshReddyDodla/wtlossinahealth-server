from fastapi import APIRouter

router = APIRouter(prefix="/smbg", tags=["V1 - SMBG Reports"])

from .list import *
