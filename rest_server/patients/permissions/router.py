from fastapi import APIRouter

router = APIRouter(prefix="/permissions", tags=["Patient - Permissions"])

from .read import *
from .update import *
