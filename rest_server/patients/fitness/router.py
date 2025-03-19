from fastapi import APIRouter

router = APIRouter(prefix="/fitness", tags=["Patient - Fitness"])

from .read import *
from .upload import *
