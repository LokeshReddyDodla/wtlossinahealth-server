from fastapi import APIRouter

router = APIRouter(prefix="/sleep", tags=["V1 - Sleep Reports"])

from .list import *
from .read import *