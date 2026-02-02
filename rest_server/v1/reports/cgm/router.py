from fastapi import APIRouter

router = APIRouter(prefix="/cgm", tags=["V1 - CGM Reports"])

from .list import *
from .test import *
from .read import *