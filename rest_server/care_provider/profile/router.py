from fastapi import APIRouter

router = APIRouter(prefix="/care-providers", tags=["Care Provider"])

from .auth import *
from .create import *
from .delete import *
from .read import *
from .update import *
