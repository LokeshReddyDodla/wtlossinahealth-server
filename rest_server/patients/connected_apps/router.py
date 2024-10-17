from fastapi import APIRouter

router = APIRouter(prefix="/patient/connected-apps", tags=["ConnectedApps"])

from .create import *
from .other_app import *
from .read import *
