from fastapi import APIRouter

router = APIRouter(prefix="/patient/meals", tags=["Meals"])

from .read import *
from .upload import *
from .analyze_meal import *
from .delete import *
