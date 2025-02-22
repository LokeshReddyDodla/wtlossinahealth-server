from fastapi import APIRouter

router = APIRouter(prefix="/patient/package", tags=["Patient - Package"])

from .read import *
