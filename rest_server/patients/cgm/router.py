from fastapi import APIRouter

router = APIRouter(prefix="/patient/cgm", tags=["CGM"])

from .upload import *
from .report import *
from .delete import *