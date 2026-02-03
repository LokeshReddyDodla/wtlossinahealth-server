"""Payload building utilities for vector services."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .constants import TIME_BUCKETS
from .exceptions import PayloadValidationError

logger = logging.getLogger(__name__)


class PayloadBuilder:
    """Utility class for building standardized vector payloads."""

    @staticmethod
    def bucket_time(hour: int) -> str:
        """
        Map hour to time bucket.

        Args:
            hour: Hour of day (0-23)

        Returns:
            Time bucket name: "morning", "afternoon", "evening", or "night"
        """
        if 6 <= hour < 12:
            return "morning"
        elif 12 <= hour < 18:
            return "afternoon"
        elif 18 <= hour < 24:
            return "evening"
        else:
            return "night"

    @staticmethod
    def time_buckets_for_range(start_time: datetime, end_time: datetime) -> List[str]:
        """
        Calculate time buckets for a time range.

        Args:
            start_time: Start datetime
            end_time: End datetime

        Returns:
            List of time bucket names
        """
        buckets = set()

        # If start and end are the same day
        if start_time.date() == end_time.date():
            for hour in range(start_time.hour, end_time.hour + 1):
                buckets.add(PayloadBuilder.bucket_time(hour))
        else:
            # If range spans multiple days → treat as "all_day"
            buckets = {"all_day"}

        return sorted(buckets)

    @staticmethod
    def build_base_payload(
        patient_id: str,
        patient_age: int,
        patient_gender: str,
        data_type: str,
        text_repr: str,
        start_time: datetime,
        end_time: datetime,
        report_id: Optional[str] = None,
        additional_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build standardized base payload for vector points.

        Args:
            patient_id: Patient identifier
            patient_age: Patient age
            patient_gender: Patient gender
            data_type: Data type identifier
            text_repr: Text representation for embedding
            start_time: Start datetime
            end_time: End datetime
            report_id: Optional report identifier
            additional_payload: Optional additional payload fields

        Returns:
            Standardized payload dictionary

        Raises:
            PayloadValidationError: If validation fails
        """
        # Validate required fields
        if not patient_id:
            raise PayloadValidationError("patient_id is required", field="patient_id")
        if not data_type:
            raise PayloadValidationError("data_type is required", field="data_type")
        if text_repr is None:
            raise PayloadValidationError("text_repr is required", field="text_repr")

        payload: Dict[str, Any] = {
            "patient_id": patient_id,
            "patient_age": patient_age,
            "patient_gender": patient_gender,
            "data_type": data_type,
            "text_repr": text_repr,
            "start_time": int(start_time.timestamp() * 1000),
            "end_time": int(end_time.timestamp() * 1000),
            "date": start_time.date().isoformat(),
            "day_of_week": start_time.weekday(),
            "is_weekend": start_time.weekday() >= 5,
            "week_number": start_time.isocalendar()[1],
            "month": start_time.month,
            "time_of_day_bucket": PayloadBuilder.time_buckets_for_range(
                start_time, end_time
            ),
        }

        if report_id:
            payload["report_id"] = report_id

        if additional_payload:
            payload.update(additional_payload)

        return payload
