from fastapi import APIRouter

router = APIRouter(prefix="/packages", tags=["Care Provider"])

from .create import *
from .read import *
