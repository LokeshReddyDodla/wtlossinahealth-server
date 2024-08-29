from fastapi import APIRouter

router = APIRouter(prefix="/patient/profile", tags=["Profile"])

from .read import *
from .create import *
from .update import *
from .delete import *
