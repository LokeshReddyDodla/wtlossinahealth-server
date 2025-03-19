from fastapi import APIRouter

router = APIRouter(prefix="/package", tags=["Patient - Package"])

from .read import *
