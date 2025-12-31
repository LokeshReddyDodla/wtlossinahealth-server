from fastapi import APIRouter

router = APIRouter(prefix="/care_providers", tags=["V1 - Care Providers"])

from .list import *

