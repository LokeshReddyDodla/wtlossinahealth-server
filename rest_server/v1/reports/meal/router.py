from fastapi import APIRouter

router = APIRouter(prefix="/meal", tags=["V1 - Meal Reports"])

from .list import *
from .read import *
from .test import *