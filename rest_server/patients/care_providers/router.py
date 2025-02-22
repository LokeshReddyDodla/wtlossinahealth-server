from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/care-providers", tags=["Patient - Care Providers"]
)


from .create import *
from .read import *