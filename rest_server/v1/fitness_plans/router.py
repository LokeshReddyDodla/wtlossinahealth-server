from fastapi import APIRouter

router = APIRouter(prefix="/fitness-plans", tags=["Fitness Plans"])

from .create import *
from .read import *
from .list import *
from .update import *
from .delete import *
from .utilities import *
