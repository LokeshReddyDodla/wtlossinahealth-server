from fastapi import APIRouter

router = APIRouter(
    prefix="/health-facility", tags=["Admin - Health Facility"]
)

from .create import *
from .delete import *
from .read import *
