from fastapi import APIRouter

router = APIRouter(prefix="/medications", tags=["Medications"])

from .read import *
from .update import *
from .adherence import *
