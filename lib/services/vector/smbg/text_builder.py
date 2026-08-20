"""Text representation builder for SMBG data."""

from lib.services.clinical_constants import (
    GLUCOSE_HYPER_MGDL,
    GLUCOSE_HYPO_MGDL,
    GLUCOSE_SEVERE_HYPER_MGDL,
)
from datetime import datetime
from typing import Any, Dict


class SMBGTextReprBuilder:
    """Builder for creating text representations of SMBG readings."""

    @staticmethod
    def build(reading: Dict[str, Any]) -> str:
        """
        Build text representation for an SMBG reading.

        Args:
            reading: SMBG reading data dictionary

        Returns:
            Text representation string
        """
        glucose = reading.get("glucose_mgdl", 0)
        reading_type = (reading.get("type") or "unspecified").lower()
        reading_time = reading.get("reading_time")
        notes = (reading.get("notes") or "").strip()
        source = reading.get("source", "app")

        dt = None
        try:
            dt = datetime.fromisoformat(str(reading_time))
        except Exception:
            pass

        date_str = dt.strftime("%Y-%m-%d") if dt else "unknown date"
        time_str = dt.strftime("%H:%M") if dt else "unknown time"

        text_parts = [
            f"Blood glucose reading ({reading_type}).",
            f"Glucose level: {glucose} mg/dL.",
            f"Recorded on {date_str} at {time_str}.",
            f"Source: {source}.",
        ]

        if notes:
            text_parts.append(f"Notes: {notes}")

        # Add health interpretation
        text_parts.append(
            SMBGTextReprBuilder._interpret_glucose(glucose, reading_type)
        )

        return " ".join(text_parts)

    @staticmethod
    def _interpret_glucose(glucose: float, reading_type: str) -> str:
        """
        Generate a health-related interpretation for embedding context.

        Args:
            glucose: Glucose value in mg/dL
            reading_type: Type of reading (e.g., "pre-meal", "post-meal")

        Returns:
            Interpretation string
        """
        # Same ADA bands the SMBG report uses — the RAG text and the report
        # must not disagree about whether a reading was in range.
        if glucose < GLUCOSE_HYPO_MGDL:
            condition = "low (hypoglycemia)"
        elif glucose <= GLUCOSE_HYPER_MGDL:
            condition = "within target range (70-180 mg/dL)"
        elif glucose <= GLUCOSE_SEVERE_HYPER_MGDL:
            condition = "high (hyperglycemia)"
        else:
            condition = "very high (severe hyperglycemia)"

        return (
            f"The glucose reading is {condition} for a {reading_type} reading."
        )
