from fastapi import APIRouter

router = APIRouter(prefix="/cgm", tags=["Patient - CGM"])

from .read import *
from .report import *
from .upload import *
