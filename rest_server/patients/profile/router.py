from fastapi import APIRouter

router = APIRouter(prefix="/patient/profile", tags=["Patient - Profile"])

from .create import *
from .delete import *
from .read import *
from .update import *
