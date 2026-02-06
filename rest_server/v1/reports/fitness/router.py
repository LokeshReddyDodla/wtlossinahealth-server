from fastapi import APIRouter

router = APIRouter(prefix="/fitness", tags=["V1 - Fitness Reports"])

from .list import *
from .read import *
from .test import *