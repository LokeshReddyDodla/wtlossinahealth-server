from fastapi import APIRouter

router = APIRouter(prefix="/meal", tags=["V1 - Meal Agent"])

from .respond import *
from .read import *
