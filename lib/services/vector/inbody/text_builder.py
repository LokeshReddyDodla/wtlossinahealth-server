"""Text representation builder for InBody body-composition reports.

The input is the ``InbodyExtraction`` dict stored on
``patient_inbody_reports.analysis`` (see ``lib/schemas/inbody.py``).
"""

from typing import Any, Dict, List, Optional


class InbodyTextReprBuilder:
    """Builder for creating text representations of InBody scans."""

    @staticmethod
    def build(
        analysis: Dict[str, Any],
        report_date: Optional[str],
        needs_review: bool = False,
    ) -> str:
        """
        Build text representation for one InBody scan.

        Args:
            analysis: InbodyExtraction dict (measurements, evaluations, ...)
            report_date: ISO date of the scan
            needs_review: True when extraction confidence was low

        Returns:
            Text representation string
        """
        text_parts: List[str] = []

        date_str = report_date or "unknown date"
        device = analysis.get("device_model")
        header = f"InBody body-composition scan on {date_str}"
        if device:
            header += f" ({device})"
        text_parts.append(header + ".")

        score = analysis.get("inbody_score")
        if score is not None:
            text_parts.append(f"InBody score: {score}/100.")

        measurement_lines = [
            InbodyTextReprBuilder._format_measurement(m)
            for m in analysis.get("measurements") or []
        ]
        measurement_lines = [line for line in measurement_lines if line]
        if measurement_lines:
            text_parts.append(
                "Measurements: " + ", ".join(measurement_lines) + "."
            )

        weight_control = analysis.get("weight_control") or {}
        control_parts = []
        if weight_control.get("target_weight_kg") is not None:
            control_parts.append(
                f"target weight {weight_control['target_weight_kg']} kg"
            )
        for key, label in (
            ("weight_control_kg", "weight change"),
            ("fat_control_kg", "fat change"),
            ("muscle_control_kg", "muscle change"),
        ):
            if weight_control.get(key) is not None:
                control_parts.append(
                    f"recommended {label} {weight_control[key]:+} kg"
                )
        if control_parts:
            text_parts.append(
                "Weight control targets: " + ", ".join(control_parts) + "."
            )

        for section_key, section_label in (
            ("nutrition_evaluation", "Nutritional evaluation"),
            ("obesity_evaluation", "Obesity evaluation"),
            ("body_balance_evaluation", "Body balance"),
        ):
            section_line = InbodyTextReprBuilder._format_evaluation(
                analysis.get(section_key), section_label
            )
            if section_line:
                text_parts.append(section_line)

        segmental_line = InbodyTextReprBuilder._format_segmental(
            analysis.get("segmental_lean") or [], "lean mass"
        )
        if segmental_line:
            text_parts.append(segmental_line)
        segmental_fat_line = InbodyTextReprBuilder._format_segmental(
            analysis.get("segmental_fat") or [], "fat mass"
        )
        if segmental_fat_line:
            text_parts.append(segmental_fat_line)

        impedance_note = analysis.get("impedance_note")
        if impedance_note:
            text_parts.append(f"Impedance: {impedance_note}")

        if needs_review:
            text_parts.append(
                "(Low extraction confidence — values flagged for review.)"
            )

        return " ".join(text_parts)

    @staticmethod
    def _format_measurement(measurement: Dict[str, Any]) -> str:
        name = (measurement.get("name") or "").replace("_", " ").strip()
        value = measurement.get("value")
        if not name or value is None:
            return ""
        unit = measurement.get("unit") or ""
        line = f"{name}: {value}{' ' + unit if unit else ''}"

        low = measurement.get("normal_range_low")
        high = measurement.get("normal_range_high")
        if low is not None and high is not None:
            line += f" (normal {low}-{high})"

        level = measurement.get("level")
        if level and level != "normal":
            line += f" [{level}]"
        return line

    @staticmethod
    def _format_evaluation(
        section: Optional[Dict[str, Any]], label: str
    ) -> str:
        if not section:
            return ""
        ratings = [
            f"{key.replace('_', ' ')}: {value.replace('_', ' ')}"
            for key, value in section.items()
            if key != "summary" and isinstance(value, str)
        ]
        parts = []
        if ratings:
            parts.append(", ".join(ratings))
        if section.get("summary"):
            parts.append(section["summary"])
        if not parts:
            return ""
        return f"{label}: " + "; ".join(parts) + "."

    @staticmethod
    def _format_segmental(
        segments: List[Dict[str, Any]], label: str
    ) -> str:
        # Only the notable segments make it into the narrative — full
        # per-segment numbers live in the structured analysis, and an
        # all-normal grid adds no semantic signal for retrieval.
        notable = [
            seg
            for seg in segments
            if seg.get("level") and seg.get("level") != "normal"
        ]
        if not notable:
            return ""
        seg_parts = []
        for seg in notable:
            name = (seg.get("segment") or "").replace("_", " ")
            part = f"{name} {seg.get('level')}"
            if seg.get("percent_of_normal") is not None:
                part += f" ({seg['percent_of_normal']}% of ideal)"
            seg_parts.append(part)
        return f"Segmental {label} out of range: " + ", ".join(seg_parts) + "."
