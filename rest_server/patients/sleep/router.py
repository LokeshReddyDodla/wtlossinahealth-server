from fastapi import APIRouter

router = APIRouter(prefix="/sleep", tags=["Patient - Sleep"])

from .read import *
