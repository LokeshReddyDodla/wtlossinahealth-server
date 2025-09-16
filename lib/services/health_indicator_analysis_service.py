from typing import Dict, List, Optional
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.postgres_store import PostgresStore
from lib.models.patient import Patient
from lib.models.weight_loss_agent import (
    HealthIndicator,
    InbodyMeasurement,
    InbodyReport,
    NormalRange,
    WeightLossAgentEnrollment,
)
from lib.schemas.weight_loss_agent import HealthIndicator as HealthIndicatorSchema
from lib.services.ai_conversation_service.system_messages.weight_loss_agent_system_message import (
    WeightLossAgentSystemMessage,
)
from openai import AsyncOpenAI


class HealthIndicatorAnalysisService:
    """Service for AI-powered analysis of health indicators from inbody measurements"""

    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store
        self.client = AsyncOpenAI()

    async def analyze_health_indicators(
        self, measurements: List[InbodyMeasurement], patient: Patient
    ) -> List[HealthIndicator]:
        """Analyze measurements and create health indicators with basic analysis"""

        health_indicators = []

        for measurement in measurements:
            # Use the normal ranges already stored in the measurement
            normal_min = measurement.normal_min
            normal_max = measurement.normal_max

            # Determine if measurement is abnormal
            is_abnormal = False
            abnormality_level = None
            analysis_explanation = f"Measurement {measurement.measurement_type}: {measurement.value} {measurement.unit}"

            if normal_min is not None and normal_max is not None:
                if measurement.value < normal_min:
                    is_abnormal = True
                    abnormality_level = "low"
                    analysis_explanation += f" (below normal range {normal_min}-{normal_max})"
                elif measurement.value > normal_max:
                    is_abnormal = True
                    abnormality_level = "high"
                    analysis_explanation += f" (above normal range {normal_min}-{normal_max})"
                else:
                    analysis_explanation += f" (within normal range {normal_min}-{normal_max})"

            # Create health indicator
            health_indicator = HealthIndicator(
                report_id=measurement.report_id,
                indicator_name=str(measurement.measurement_type),
                indicator_type="measurement",
                value=measurement.value,
                unit=str(measurement.unit),
                is_abnormal=is_abnormal,
                abnormality_level=abnormality_level,
                normal_range_min=normal_min,
                normal_range_max=normal_max,
                analysis_explanation=analysis_explanation,
            )

            health_indicators.append(health_indicator)

        return health_indicators
