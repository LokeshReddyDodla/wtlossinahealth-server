from fastapi import APIRouter

router = APIRouter(prefix="/documents", tags=["V1 - Documents"])

from .create import *
from .read import *
