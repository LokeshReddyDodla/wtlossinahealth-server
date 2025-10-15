from fastapi import APIRouter

router = APIRouter(
    prefix="/profiles",
    tags=["Care Provider - Profiles"],
)

from .create import *
from .delete import *
from .read import *
from .update import *
