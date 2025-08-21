import traceback
from datetime import date, datetime

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_cgm_report_service,
    get_fitness_stats_processor,
    get_meal_report_service,
    get_patient_profile_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.patient import CorePatientProfile
from lib.services.cgm_report_service import CGMReportService
from lib.services.meal_report_service import MealReportService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router
