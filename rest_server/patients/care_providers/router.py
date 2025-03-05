from fastapi import APIRouter

router = APIRouter(
    prefix="/patient/care-providers", tags=["Patient - Care Providers"]
)


from .create import *
from .read import *