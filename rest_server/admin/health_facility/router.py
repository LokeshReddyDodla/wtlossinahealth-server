from fastapi import APIRouter

router = APIRouter(
    prefix="/admin/health-facility", tags=["Admin - Health Facility"]
)

from .create import *
from .delete import *
from .read import *
