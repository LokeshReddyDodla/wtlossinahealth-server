from fastapi import APIRouter

router = APIRouter(prefix="/packages", tags=["Patient - Package"])

from .read import *
from .create import *
