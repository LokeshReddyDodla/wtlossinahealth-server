from fastapi import APIRouter

router = APIRouter(prefix="/patient/fitness", tags=["Fitness"])

from .read import *
from .upload import *
from .report import *
from .test import *
