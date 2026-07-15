from fastapi import APIRouter

router = APIRouter(prefix="/reports", tags=["Admin - Reports"])

from .regenerate import *
