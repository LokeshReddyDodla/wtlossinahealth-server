from fastapi import APIRouter

router = APIRouter(prefix="/care-providers", tags=["Patient - Care Providers"])


from .create import *
from .read import *
