from fastapi import APIRouter

router = APIRouter(prefix="/patient/cgm", tags=["CGM"])

from .delete import *
from .read import *
from .report import *
from .upload import *
