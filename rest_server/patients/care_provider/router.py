from fastapi import APIRouter

router = APIRouter(
    prefix="/patients/care-providers", tags=["Patient Care Providers"]
)

from .read import *
from .create import *
from .update import *
from .delete import *
