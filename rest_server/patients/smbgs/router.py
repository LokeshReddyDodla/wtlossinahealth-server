from fastapi import APIRouter

router = APIRouter(prefix="/smbgs", tags=["Patient - SMBGs"])

from .read import *
from .upload import *
