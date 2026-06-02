from fastapi import APIRouter

router = APIRouter(prefix="/share", tags=["V1 - Share"])

from .daily import *
