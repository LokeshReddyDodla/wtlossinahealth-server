"""Service for managing weight loss agent functionality."""
import re
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy import and_, func
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload, joinedload

from lib.core.clickhouse_store import ClickHouseStore
from lib.core.mongo_store import MongoStore
from lib.core.postgres_store import PostgresStore
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.patient_profile_service import PatientProfileService
from lib.services.token_usage_service import TokenUsageService
from lib.services.weightloss_agent.analytics_service import AnalyticsService
from lib.services.weightloss_agent.chat_service import ChatMixin
from lib.services.weightloss_agent.daily_reports_service import DailyReportsMixin
from lib.services.weightloss_agent.enrollment_service import EnrollmentMixin
from lib.services.weightloss_agent.inbody_reports_service import (
    InbodyReportsMixin,
)
from lib.services.weightloss_agent.progress_analysis_service import (
    ProgressAnalysisMixin,
)


class WeightLossAgentService(
    EnrollmentMixin,
    InbodyReportsMixin,
    DailyReportsMixin,
    ProgressAnalysisMixin,
    ChatMixin,
):
    """Service for managing weight loss agent functionality"""

    CONFIRMATION_THRESHOLD = 0.85

    def __init__(
        self,
        postgres_store: PostgresStore,
        clickhouse_store: ClickHouseStore,
        reports_collection: MongoStore,
        interactions_collection: MongoStore,
        progress_analyses_collection: MongoStore,
        patient_profile_service: PatientProfileService,
        care_provider_profile_service: CareProviderProfileService,
        analytics_service: AnalyticsService,
        token_usage_service: TokenUsageService,
    ):
        self.postgres_store = postgres_store
        self.clickhouse_store = clickhouse_store
        self.reports_collection = reports_collection
        self.interactions_collection = interactions_collection
        self.progress_analyses_collection = progress_analyses_collection
        self.patient_profile_service = patient_profile_service
        self.care_provider_profile_service = care_provider_profile_service
        self.analytics_service = analytics_service
        self.token_usage_service = token_usage_service
