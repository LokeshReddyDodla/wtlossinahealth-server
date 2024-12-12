from fastapi import APIRouter

router = APIRouter(prefix="/admin/health-facility", tags=["Health Facility"])


from .create import *
from .delete import *
