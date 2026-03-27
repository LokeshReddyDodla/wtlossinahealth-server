from fastapi import APIRouter

router = APIRouter(prefix="/uploads", tags=["V1 - Uploads"])

from .libreview import *
from .linx import *
from .sinocare import *
