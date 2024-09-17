from fastapi import APIRouter

router = APIRouter(
    prefix="/admin/care-providers/profile",
    tags=["Admin Care Provider Profile"],
)

from .create import *
