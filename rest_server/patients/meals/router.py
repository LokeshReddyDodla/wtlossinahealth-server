from fastapi import APIRouter

router = APIRouter(prefix="/meals", tags=["Patient - Meals"])

from .delete import *
from .read import *
from .report import *
from .upload import *
from .update import *
