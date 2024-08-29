from fastapi import APIRouter

router = APIRouter(prefix="/patient/connected-apps", tags=["ConnectedApps"])

from .read import *
from .libreview import *
from .other_app import *
