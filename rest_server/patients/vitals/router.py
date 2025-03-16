from fastapi import APIRouter

router = APIRouter(prefix="/vitals", tags=["Patient - Vitals"])

from .read import *
from .upload import *
