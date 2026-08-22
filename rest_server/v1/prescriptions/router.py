from fastapi import APIRouter

router = APIRouter(prefix="/prescriptions", tags=["Prescriptions"])

from .preview import *
from .confirm import *
from .read import *
from .delete import *
from .edit import *
from .safety_check import *
from .send import *
