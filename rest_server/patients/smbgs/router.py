from fastapi import APIRouter

router = APIRouter(prefix="/patient/smbgs", tags=["SMBGs"])

from .read import *
from .upload import *
