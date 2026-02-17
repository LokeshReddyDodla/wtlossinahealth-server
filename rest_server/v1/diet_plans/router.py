from fastapi import APIRouter

router = APIRouter(prefix="/diet-plans", tags=["Diet Plans"])

from .create import *
from .read import *
from .list import *
from .update import *
from .delete import *
from .utilities import *
