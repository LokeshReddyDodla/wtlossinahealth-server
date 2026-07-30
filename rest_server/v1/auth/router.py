from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["V1 - Auth"])

from .devices import *
from .firebase_login import *
from .login import *
from .logout import *
