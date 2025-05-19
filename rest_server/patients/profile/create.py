from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.schemas.patient import Patient as PatientSchema
from lib.schemas.patient import PatientCreate
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router
