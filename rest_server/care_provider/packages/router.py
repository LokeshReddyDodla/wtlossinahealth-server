from fastapi import APIRouter

router = APIRouter(prefix="/packages", tags=["Care Provider - Packages"])

from .create import *
from .delete import *
from .read import *
from .update import *
