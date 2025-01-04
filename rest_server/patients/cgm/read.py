import traceback
import uuid
from datetime import date, datetime, time, timedelta
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_glucose_stats_processor
from lib.models.patient import Patient
from lib.utils.date.periods import OverallPeriod
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router
