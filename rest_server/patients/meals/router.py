from fastapi import APIRouter

router = APIRouter(prefix="/meals", tags=["Patient - Meals"])

from .analyze_meal import *
from .delete import *
from .read import *
from .report import *
from .upload import *
