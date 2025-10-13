from datetime import datetime
from typing import Any, Dict


class SMBGTextReprBuilder:
    @staticmethod
    def build(reading: Dict[str, Any]) -> str:
        glucose = reading.get("glucose_mgdl", 0)
        reading_type = (reading.get("type") or "unspecified").lower()
        reading_time = reading.get("reading_time")
        notes = reading.get("notes", "").strip()
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
        """Generate a health-related interpretation for embedding context."""
        if glucose < 70:
            condition = "low (hypoglycemia)"
        elif 70 <= glucose <= 130:
            condition = "within normal range"
        elif 130 < glucose <= 180:
            condition = "slightly high"
        else:
            condition = "high (hyperglycemia)"

        return (
            f"The glucose reading is {condition} for a {reading_type} reading."
        )
