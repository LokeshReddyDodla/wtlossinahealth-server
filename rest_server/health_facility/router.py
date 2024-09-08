from fastapi import APIRouter

router = APIRouter(
    prefix="/health-health_facilities", tags=["Health Facilities"]
)

from .read import *
from .create import *
from .update import *
from .delete import *
