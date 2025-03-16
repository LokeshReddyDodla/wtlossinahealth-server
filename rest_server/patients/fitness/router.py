from fastapi import APIRouter

router = APIRouter(prefix="/fitness", tags=["Patient - Fitness"])

from .read import *
from .test import *
from .upload import *
