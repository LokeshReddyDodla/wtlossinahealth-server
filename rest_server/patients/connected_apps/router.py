from fastapi import APIRouter

router = APIRouter(
    prefix="/patient/connected-apps", tags=["Patient - Connected Apps"]
)

from .other_app import *
from .read import *
from .update import *
