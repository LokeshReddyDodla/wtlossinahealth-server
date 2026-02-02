"""Point ID generation utilities for vector services."""

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from .exceptions import PointIdGenerationError

logger = logging.getLogger(__name__)


class PointIdGenerator:
    """Utility class for generating consistent point IDs."""

    @staticmethod
    def generate(
        patient_id: str,
        data_type: str,
        start_time: datetime,
        end_time: datetime,
        report_id: Optional[str] = None,
        additional_suffix: Optional[str] = None,
        additional_payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate a unique point ID using MD5 hash.

        Args:
            patient_id: Patient identifier
            data_type: Data type identifier
            start_time: Start datetime
            end_time: End datetime
            report_id: Optional report identifier
            additional_suffix: Optional additional suffix for uniqueness
            additional_payload: Optional payload for event-specific hashing

        Returns:
            MD5 hash string (32 characters)

        Raises:
            PointIdGenerationError: If generation fails
        """
        try:
            # Build base identifier
            parts = [
                patient_id,
                report_id or "",
                data_type,
                start_time.isoformat(),
                end_time.isoformat(),
            ]

            # Add data type specific suffixes
            if data_type == "agp_point":
                hour = (
                    additional_payload.get("hour")
                    if additional_payload
                    else None
                )
                if hour is not None:
                    parts.append(f"hour_{hour}")

            elif data_type == "time_period_stats":
                period_name = (
                    additional_payload.get("time_period")
                    if additional_payload
                    else None
                )
                if period_name:
                    parts.append(f"period_{period_name}")

            elif data_type == "cgm_semantic_window":
                bucket_start = start_time.isoformat()
                parts.append(f"bucket_{bucket_start}")

            elif data_type.endswith("_event"):
                if additional_payload:
                    # Use hash of payload for event uniqueness
                    event_hash = hashlib.md5(
                        json.dumps(additional_payload, sort_keys=True).encode()
                    ).hexdigest()[:8]
                    parts.append(event_hash)

            # Add custom suffix if provided
            if additional_suffix:
                parts.append(additional_suffix)

            # Join and hash
            base_string = "-".join(str(p) for p in parts if p)
            return hashlib.md5(base_string.encode()).hexdigest()

        except Exception as e:
            raise PointIdGenerationError(
                f"Failed to generate point ID: {e}",
                patient_id=patient_id,
                data_type=data_type,
            ) from e

    @staticmethod
    def generate_simple(entity_id: str) -> str:
        """
        Generate a simple point ID from entity ID.

        Args:
            entity_id: Entity identifier (e.g., meal_id, reading_id)

        Returns:
            MD5 hash string (32 characters)
        """
        return hashlib.md5(entity_id.encode()).hexdigest()
