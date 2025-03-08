from fastapi import APIRouter

router = APIRouter(
    prefix="/admin/patient/meals",
    tags=["Admin - Patient Meals"],
)

from .read import *
