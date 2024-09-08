from fastapi import APIRouter

router = APIRouter(
    prefix="/health-facilities", tags=["Health Facilities"]
)

from .read import *
from .create import *
from .update import *
from .delete import *
