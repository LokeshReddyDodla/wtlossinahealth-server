from fastapi import APIRouter

router = APIRouter(prefix="/care-providers", tags=["Care Providers"])

from .read import *
from .create import *
from .update import *
from .delete import *
