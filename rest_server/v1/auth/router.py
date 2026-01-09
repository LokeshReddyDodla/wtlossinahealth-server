from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["V1 - Auth"])

from .login import *
from .logout import *
from .otp import *
