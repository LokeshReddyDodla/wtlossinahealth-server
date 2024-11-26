from fastapi import APIRouter

router = APIRouter(
    prefix="/care-providers/profile", tags=["Care Provider Profile"]
)

from .auth import *
from .create import *
from .delete import *
from .read import *
from .update import *
