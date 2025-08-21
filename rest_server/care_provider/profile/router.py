from fastapi import APIRouter

router = APIRouter(
    prefix="/care-providers/profiles",
    tags=["Care Provider - Profiles"],
)

from .create import *
from .delete import *
from .read import *
from .update import *
