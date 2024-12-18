from fastapi import APIRouter

router = APIRouter(prefix="/patient/smbgs", tags=["Patient - SMBGs"])

from .read import *
from .upload import *
