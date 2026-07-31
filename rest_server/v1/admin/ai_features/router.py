from fastapi import APIRouter

router = APIRouter(prefix="/admin/ai-features", tags=["V1 - Admin AI Features"])

from .read import *
from .update import *
