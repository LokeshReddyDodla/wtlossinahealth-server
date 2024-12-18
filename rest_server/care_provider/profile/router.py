from fastapi import APIRouter

router = APIRouter(prefix="/profile", tags=["Care Provider - Profile"])

from .create import *
from .delete import *
from .read import *
from .update import *
