"""Inbody report handling mixin for weight loss agent workflows."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy import and_
from sqlalchemy.future import select

from lib.models.weight_loss_agent import WeightLossAgentEnrollment
from lib.schemas.weight_loss_agent import (
    InbodyReportAnalysisResult,
    InbodyReportCreate,
)
from lib.utils.http_exceptions import raise_http_exception


class InbodyReportsMixin:
    async def create_inbody_report(
        self,
        enrollment_id: UUID,
        report_data: InbodyReportCreate,
    ) -> Dict:
        """Create a new inbody report - MongoDB"""

        # Verify enrollment exists and is active (in PostgreSQL)
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(WeightLossAgentEnrollment).where(
                    and_(
                        WeightLossAgentEnrollment.enrollment_id
                        == enrollment_id,
                        WeightLossAgentEnrollment.is_active == True,
                    )
                )
            )
            enrollment = result.scalar_one_or_none()

            if not enrollment:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Active enrollment not found",
                )

            patient_id = str(enrollment.patient_id)

        # Create inbody report document
        report_doc = {
            "report_id": str(uuid4()),
            "enrollment_id": str(enrollment_id),
            "patient_id": patient_id,
            "ai_summary": report_data.ai_summary,
            "original_filename": report_data.original_filename,
            "file_size": report_data.file_size,
            "content_type": report_data.content_type,
            "report_date": report_data.report_date,
            "extracted_at": datetime.now(),
            "processed": False,
            "created_at": datetime.now(),
            "measurements": [],  # Will be populated by analysis
            "health_indicators": [],  # Will be populated by analysis
        }

        # Insert into MongoDB
        await self.reports_collection.insert_one(report_doc)

        # Remove MongoDB _id
        report_doc.pop("_id", None)

        return report_doc

    async def get_latest_inbody_report_with_details(
        self, enrollment_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Fetch latest inbody report with highlighted measurements - MongoDB"""

        report = await self.reports_collection.find_one(
            {"enrollment_id": str(enrollment_id)}, sort=[("report_date", -1)]
        )

        if not report:
            return None

        prepared_report = self._prepare_report_document(report)
        highlights = self._extract_report_highlights(prepared_report)

        return {
            "report": prepared_report,
            "highlights": highlights,
        }

    def _prepare_report_document(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize MongoDB report document for API responses"""

        prepared = dict(report)
        prepared.pop("_id", None)

        report_id = prepared.get("report_id")
        created_at = prepared.get("created_at", datetime.now())

        raw_measurements = prepared.get("measurements") or []
        measurements: List[Dict[str, Any]] = []
        for measurement in raw_measurements:
            measurement_copy = dict(measurement)
            measurement_copy.setdefault("measurement_id", str(uuid4()))
            measurement_copy.setdefault("report_id", report_id)
            measurement_copy.setdefault("created_at", created_at)
            measurements.append(measurement_copy)
        prepared["measurements"] = measurements

        raw_indicators = prepared.get("health_indicators") or []
        indicators: List[Dict[str, Any]] = []
        for indicator in raw_indicators:
            indicator_copy = dict(indicator)
            indicator_copy.setdefault("indicator_id", str(uuid4()))
            indicator_copy.setdefault("report_id", report_id)
            indicator_copy.setdefault("created_at", created_at)
            indicators.append(indicator_copy)
        prepared["health_indicators"] = indicators

        return prepared

    def _extract_report_highlights(
        self, report: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Derive highlight metrics used by the UI from measurement data"""

        measurements = report.get("measurements") or []
        measurement_lookup = self._build_measurement_lookup(measurements)

        highlight_sources = {
            "skeletal_muscle_mass": [
                "skeletal_muscle_mass",
                "muscle_mass",
                "skeletal_muscle",
            ],
            "body_fat_percentage": [
                "body_fat_percentage",
                "percentage_body_fat",
                "body_fat",
            ],
            "visceral_fat_level": [
                "visceral_fat_level",
                "visceral_fat",
            ],
            "basal_metabolic_rate": [
                "basal_metabolic_rate",
                "bmr",
            ],
        }

        highlights: Dict[str, Any] = {}
        for field, keys in highlight_sources.items():
            measurement = None
            for key in keys:
                measurement = measurement_lookup.get(key)
                if measurement:
                    break
            highlights[field] = self._format_measurement_summary(measurement)

        highlights["segment_lean_analysis"] = self._collect_segment_lean_measurements(
            measurements
        )

        return highlights

    def _build_measurement_lookup(
        self, measurements: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        lookup: Dict[str, Dict[str, Any]] = {}
        for measurement in measurements:
            measurement_type = (measurement.get("measurement_type") or "").strip()
            if not measurement_type:
                continue
            normalized_key = self._normalize_measurement_key(measurement_type)
            if normalized_key:
                lookup[normalized_key] = measurement
        return lookup

    def _normalize_measurement_key(self, value: str) -> str:
        """Normalize measurement label to enable lookups"""

        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

    def _format_measurement_summary(
        self, measurement: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if not measurement:
            return None

        return {
            "label": measurement.get("measurement_type"),
            "value": measurement.get("value"),
            "unit": measurement.get("unit"),
            "normal_min": measurement.get("normal_min"),
            "normal_max": measurement.get("normal_max"),
            "confidence_score": measurement.get("confidence_score"),
        }

    def _collect_segment_lean_measurements(
        self, measurements: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Return lean measurements for body segments (arms, legs, trunk)"""

        segment_entries: List[Dict[str, Any]] = []
        segment_keywords = ["arm", "leg", "trunk", "segment"]

        for measurement in measurements:
            label = (measurement.get("measurement_type") or "").lower()
            if not label:
                continue
            if "lean" not in label:
                continue
            if not any(keyword in label for keyword in segment_keywords):
                continue

            summary = self._format_measurement_summary(measurement)
            if summary:
                segment_entries.append(summary)

        return segment_entries

    def _extract_segmental_lean_from_text(
        self, ai_response_text: str
    ) -> List[Dict[str, Any]]:
        """Parse AI response text for segmental lean analysis values"""

        segment_entries: List[Dict[str, Any]] = []
        seen_keys = set()

        patterns = [
            re.compile(
                r"\b(?P<side>right|left|r|l)\s*(?P<bodypart>arm|leg)\b[^0-9]{0,20}(?P<value>[\d.]+)\s*(?P<unit>kg|lbs?|kilograms?|pounds?)",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?P<bodypart>trunk|torso|core|whole\s*body)\b[^0-9]{0,20}(?P<value>[\d.]+)\s*(?P<unit>kg|lbs?|kilograms?|pounds?)",
                re.IGNORECASE,
            ),
        ]

        for pattern in patterns:
            for match in pattern.finditer(ai_response_text):
                side = match.groupdict().get("side")
                bodypart = match.groupdict().get("bodypart")
                value = match.group("value")
                unit = match.group("unit") or "kg"

                label = self._format_segment_label(side, bodypart)
                if not label:
                    continue
                key = self._build_segment_metric_key(label)

                if key in seen_keys:
                    continue
                seen_keys.add(key)

                try:
                    value_number = float(value)
                except (TypeError, ValueError):
                    continue

                segment_entries.append(
                    {
                        "label": label,
                        "value": value_number,
                        "unit": unit,
                        "key": key,
                    }
                )

        return segment_entries

    def _format_segment_label(
        self, side: Optional[str], bodypart: Optional[str]
    ) -> Optional[str]:
        """Build human readable label for segmental lean measurements"""

        if not bodypart:
            return None

        normalized_side = None
        if side:
            side_lower = side.lower()
            if side_lower in ["r", "right"]:
                normalized_side = "Right"
            elif side_lower in ["l", "left"]:
                normalized_side = "Left"

        bodypart_lower = bodypart.lower()
        bodypart_map = {
            "arm": "Arm",
            "leg": "Leg",
            "trunk": "Trunk",
            "torso": "Trunk",
            "core": "Trunk",
            "wholebody": "Whole Body",
        }
        bodypart_key = bodypart_lower.replace(" ", "")
        resolved_part = bodypart_map.get(bodypart_key, None)
        if not resolved_part:
            return None

        parts = []
        if normalized_side:
            parts.append(normalized_side)
        parts.append(resolved_part)
        parts.append("Lean Mass")
        return " ".join(parts)

    def _build_segment_metric_key(self, label: str) -> str:
        """Create a normalized key for storing segmental lean measurements"""

        slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        return f"segment_{slug}"

    def _is_value_abnormal(
        self, value: float, normal_min: float, normal_max: float
    ) -> bool:
        """Check if a value is outside normal range"""

        return value < normal_min or value > normal_max

    def _get_abnormality_level(
        self, value: float, normal_min: float, normal_max: float
    ) -> Optional[str]:
        """Return low/high if value is outside range, otherwise None"""

        if value < normal_min:
            return "low"
        if value > normal_max:
            return "high"
        return None

    def _parse_normal_range(
        self, range_value: Optional[str]
    ) -> Optional[tuple[float, float]]:
        """Parse normal range string like "18.5 ~ 25.0" into floats."""

        if not range_value:
            return None

        if "~" in range_value:
            parts = range_value.split("~", 1)
            min_value = self._parse_range_bound(parts[0])
            max_value = self._parse_range_bound(parts[1])
        else:
            numbers = re.findall(r"[-+]?\d*\.?\d+", range_value)
            if len(numbers) < 2:
                return None
            min_value = float(numbers[0])
            max_value = float(numbers[1])

        if min_value is None or max_value is None:
            return None

        if min_value > max_value:
            min_value, max_value = max_value, min_value

        return min_value, max_value

    def _parse_range_bound(self, value: str) -> Optional[float]:
        match = re.search(r"[-+]?\d*\.?\d+", value)
        if not match:
            return None
        try:
            return float(match.group(0))
        except (TypeError, ValueError):
            return None

    def _extract_normal_range(
        self,
        ai_response_text: str,
        label_pattern: str,
        exclude_pattern: Optional[str] = None,
    ) -> Optional[str]:
        """Extract the normal range string (min~max) for a labeled metric."""

        if not ai_response_text:
            return None

        range_pattern = (
            r"(?:normal\s*(?:range)?\s*[:\s]*)?"
            r"(?P<range>[\d.]+\s*[~\-]\s*[\d.]+)"
        )

        for line in ai_response_text.splitlines():
            if not line.strip():
                continue
            if not re.search(label_pattern, line, re.IGNORECASE):
                continue
            if exclude_pattern and re.search(
                exclude_pattern, line, re.IGNORECASE
            ):
                continue
            range_match = re.search(range_pattern, line, re.IGNORECASE)
            if range_match:
                return range_match.group("range").replace("-", "~")

        match = re.search(
            rf"{label_pattern}.*?{range_pattern}",
            ai_response_text,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group("range").replace("-", "~")

        return None

    def _extract_measurements_table(
        self, ai_response_text: str
    ) -> Optional[Dict[str, Any]]:
        """Parse the MEASUREMENTS_TABLE section for structured metric values."""

        marker = "MEASUREMENTS_TABLE:"
        if not ai_response_text or marker not in ai_response_text:
            return None

        summary_text, table_text = ai_response_text.split(marker, 1)
        metrics: Dict[str, Any] = {}
        ranges: Dict[str, str] = {}
        key_map = {
            "weight": "weight",
            "bmi": "bmi",
            "pbf": "body_fat_percentage",
            "percent_body_fat": "body_fat_percentage",
            "body_fat_percentage": "body_fat_percentage",
            "body_fat": "body_fat_percentage",
            "skeletal_muscle_mass": "skeletal_muscle_mass",
            "smm": "skeletal_muscle_mass",
            "muscle_mass": "skeletal_muscle_mass",
            "body_fat_mass": "body_fat_mass",
            "bfm": "body_fat_mass",
            "basal_metabolic_rate": "basal_metabolic_rate",
            "bmr": "basal_metabolic_rate",
            "waist_hip_ratio": "waist_hip_ratio",
            "whr": "waist_hip_ratio",
            "visceral_fat_level": "visceral_fat_level",
            "visceral_fat": "visceral_fat_level",
            "bone_mineral_content": "bone_mineral_content",
            "bmc": "bone_mineral_content",
            "total_body_water": "total_body_water",
            "tbw": "total_body_water",
            "intracellular_water": "intracellular_water",
            "icw": "intracellular_water",
            "extracellular_water": "extracellular_water",
            "ecw": "extracellular_water",
            "body_water": "body_water",
            "target_weight": "target_weight",
        }
        null_tokens = {"null", "n/a", "na", "none"}

        for line in table_text.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 4:
                continue
            raw_key, value, unit, range_value = parts[:4]
            normalized_key = self._normalize_measurement_key(raw_key)
            metric_key = key_map.get(normalized_key)
            if not metric_key:
                continue

            value_token = value.lower()
            if not value or value_token in null_tokens:
                continue

            unit_token = unit.lower()
            metric_value = (
                f"{value} {unit}"
                if unit and unit_token not in null_tokens
                else value
            )
            metrics.setdefault(metric_key, metric_value)

            range_token = range_value.lower()
            if range_value and range_token not in null_tokens:
                if range_token != "null~null":
                    ranges.setdefault(
                        metric_key, range_value.replace(" ", "").replace("-", "~")
                    )

        return {
            "summary": summary_text.strip(),
            "metrics": metrics,
            "ranges": ranges,
        }

    def _extract_measurements_json(
        self, ai_response_text: str
    ) -> Optional[Dict[str, Any]]:
        """Parse structured JSON output for measurements and ranges."""

        if not ai_response_text:
            return None

        json_start = ai_response_text.find("{")
        json_end = ai_response_text.rfind("}")
        if json_start == -1 or json_end == -1 or json_end <= json_start:
            return None

        json_str = ai_response_text[json_start : json_end + 1]
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        metrics: Dict[str, Any] = {}
        ranges: Dict[str, str] = {}
        summary = data.get("summary") if isinstance(data, dict) else None

        key_map = {
            "weight": "weight",
            "bmi": "bmi",
            "pbf": "body_fat_percentage",
            "percent_body_fat": "body_fat_percentage",
            "body_fat_percentage": "body_fat_percentage",
            "body_fat_percent": "body_fat_percentage",
            "body_fat": "body_fat_percentage",
            "skeletal_muscle_mass": "skeletal_muscle_mass",
            "skeletal_muscle": "skeletal_muscle_mass",
            "smm": "skeletal_muscle_mass",
            "muscle_mass": "skeletal_muscle_mass",
            "body_fat_mass": "body_fat_mass",
            "bfm": "body_fat_mass",
            "basal_metabolic_rate": "basal_metabolic_rate",
            "bmr": "basal_metabolic_rate",
            "waist_hip_ratio": "waist_hip_ratio",
            "whr": "waist_hip_ratio",
            "visceral_fat_level": "visceral_fat_level",
            "visceral_fat": "visceral_fat_level",
            "bone_mineral_content": "bone_mineral_content",
            "bmc": "bone_mineral_content",
            "total_body_water": "total_body_water",
            "tbw": "total_body_water",
            "intracellular_water": "intracellular_water",
            "icw": "intracellular_water",
            "extracellular_water": "extracellular_water",
            "ecw": "extracellular_water",
            "body_water": "body_water",
            "target_weight": "target_weight",
        }

        def store_entry(
            metric_key: str,
            value: Any,
            unit: Optional[str],
            normal_min: Optional[Any],
            normal_max: Optional[Any],
        ) -> None:
            if value is None:
                return
            metric_value = (
                f"{value} {unit}".strip()
                if unit not in (None, "")
                else f"{value}"
            )
            metrics.setdefault(metric_key, metric_value)
            if normal_min is not None and normal_max is not None:
                ranges.setdefault(metric_key, f"{normal_min}~{normal_max}")

        if isinstance(data, dict):
            measurements = data.get("measurements") or []
            if isinstance(measurements, list):
                for item in measurements:
                    if not isinstance(item, dict):
                        continue
                    raw_type = (
                        item.get("measurement_type")
                        or item.get("type")
                        or item.get("measurement")
                    )
                    if not raw_type:
                        continue
                    normalized_key = self._normalize_measurement_key(
                        str(raw_type)
                    )
                    metric_key = key_map.get(normalized_key)
                    if not metric_key:
                        continue
                    store_entry(
                        metric_key,
                        item.get("value"),
                        item.get("unit"),
                        item.get("normal_min"),
                        item.get("normal_max"),
                    )

            for key, payload in data.items():
                if key == "measurements":
                    continue
                if not isinstance(payload, dict):
                    continue
                if "value" not in payload:
                    continue
                normalized_key = self._normalize_measurement_key(str(key))
                metric_key = key_map.get(normalized_key)
                if not metric_key:
                    continue
                store_entry(
                    metric_key,
                    payload.get("value"),
                    payload.get("unit"),
                    payload.get("normal_min"),
                    payload.get("normal_max"),
                )

        return {
            "summary": summary,
            "metrics": metrics,
            "ranges": ranges,
        }

    def _build_normalized_inbody_payload(
        self,
        extracted_metrics: Dict[str, Any],
        confidence_score: float,
        file_name: str = "",
        content_type: str = "",
    ) -> Dict[str, Any]:
        """Build normalized payload for InbodyReportAnalysisResult from extracted metrics"""

        values = {}
        derived = {}
        parse_confidence = {}
        confirmation_needed = []

        # Map extracted metrics to normalized values
        metric_mappings = {
            "weight": "weight_kg",
            "bmi": "bmi",
            "body_fat_percentage": "body_fat_percent",
            "body_fat": "body_fat_percent",
            "muscle_mass": "muscle_mass_kg",
            "skeletal_muscle_mass": "muscle_mass_kg",
            "body_water": "body_water_percent",
            "visceral_fat": "visceral_fat_level",
            "visceral_fat_level": "visceral_fat_level",
            "basal_metabolic_rate": "bmr_kcal",
            "target_weight": "target_weight_kg",
        }

        for original_key, normalized_key in metric_mappings.items():
            if original_key in extracted_metrics:
                try:
                    # Extract numeric value from string like "75.5 kg" or "25.3%"
                    value_str = str(extracted_metrics[original_key])
                    match = re.search(r"([\d.]+)", value_str)
                    if match:
                        values[normalized_key] = float(match.group(1))
                        parse_confidence[normalized_key] = confidence_score

                        # Flag values that need confirmation if confidence is low
                        if confidence_score < self.CONFIRMATION_THRESHOLD:
                            confirmation_needed.append(normalized_key)
                except (ValueError, TypeError):
                    pass

        # Calculate derived metrics if we have the necessary values
        if "weight_kg" in values and "bmi" in values:
            # Height can be derived from weight and BMI: height_m = sqrt(weight_kg / bmi)
            try:
                height_m = (values["weight_kg"] / values["bmi"]) ** 0.5
                derived["height_m"] = round(height_m, 2)
                derived["height_cm"] = round(height_m * 100, 1)
            except (ZeroDivisionError, ValueError):
                pass

        return {
            "values": values,
            "derived": derived,
            "parse_confidence": parse_confidence,
            "confirmation_needed": confirmation_needed,
            "provenance": {
                "source": "ai_vision_extraction",
                "file_name": file_name,
                "content_type": content_type,
                "extraction_method": "gpt-4o-vision",
            },
        }

    async def process_and_analyze_inbody_report(
        self, enrollment_id: UUID, report_file, user_id: str
    ) -> InbodyReportAnalysisResult:
        """Process uploaded inbody report file with base64 conversion first, then get AI analysis - returns GPT response first, then stores data"""

        # WORKFLOW: Base64 First → AI Analysis → User Review → Database Storage
        try:
            # Step 1: Read file content and convert to base64 FIRST
            print("Step 1: Reading file content...")
            file_content = await report_file.read()
            file_name = report_file.filename
            content_type = report_file.content_type

            print(
                f"File details: {file_name}, type: {content_type}, size: {len(file_content)} bytes"
            )

            # Convert file content to base64 for AI processing
            print("Step 2: Converting file to base64...")
            import base64

            file_content_b64 = base64.b64encode(file_content).decode("utf-8")
            print(
                f"File successfully encoded to base64, length: {len(file_content_b64)} characters"
            )

            # Validate base64 conversion
            if not file_content_b64:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Failed to convert file to base64 format",
                )

            print("Step 3: Sending image to GPT-4 Vision for analysis...")

            # Use GPT-4 Vision for image analysis
            try:
                from langchain_openai import ChatOpenAI
                from decouple import config
                from pydantic import SecretStr
                from langchain_core.messages import HumanMessage

                # Initialize GPT-4 Vision model
                vision_model = ChatOpenAI(
                    model="gpt-4o",  # GPT-4o has vision capabilities
                    temperature=0.0,
                    api_key=SecretStr(str(config("OPENAI_API_KEY"))),
                )

                # Create message with image URL for vision analysis
                # For base64 images, we need to format it properly
                image_url = f"data:{content_type};base64,{file_content_b64}"

                # Create a simpler prompt for vision analysis
                vision_prompt = """
Extract data from this InBody report image.

Return ONLY valid JSON (no markdown, no extra text) with this schema:
{
  "summary": "short 1-3 sentences",
  "overall_score": 0-100,
  "measurements": [
    {
      "measurement_type": "Weight",
      "value": 99.1,
      "unit": "kg",
      "normal_min": 41.8,
      "normal_max": 56.6
    }
  ]
}

Rules:
- Include all visible metrics in measurements, including: Weight, Skeletal Muscle Mass, Body Fat Mass, BMI, Percent Body Fat, Total Body Water, Intracellular Water, Extracellular Water, Basal Metabolic Rate, Waist-Hip Ratio, Visceral Fat Level, Bone Mineral Content, Target Weight.
- For every metric, capture the normal range if shown on the report; otherwise set normal_min and normal_max to null.
- Use numeric values for value, normal_min, and normal_max (no text or symbols).
- Use short units (kg, %, L, kcal, level).
- If a metric is missing, you may omit it or set value to null (do not invent).
"""

                # Create message with image
                message = HumanMessage(
                    content=[
                        {"type": "text", "text": vision_prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ]
                )

                # Get AI response
                ai_response_raw = await vision_model.ainvoke([message])
                ai_response_text = ai_response_raw.content

                print(
                    f"Vision analysis completed successfully. Response length: {len(ai_response_text)}"
                )

                # Parse the AI response to extract actual metric values
                confidence_score = 0.9  # Higher confidence for vision analysis
                extracted_metrics = {}
                extracted_normal_ranges = {}
                recommendations = []
                risk_factors = []
                analysis_summary = ai_response_text

                json_data = self._extract_measurements_json(ai_response_text)
                if json_data:
                    extracted_metrics.update(json_data.get("metrics", {}))
                    extracted_normal_ranges.update(
                        json_data.get("ranges", {})
                    )
                    json_summary = json_data.get("summary")
                    if isinstance(json_summary, str) and json_summary.strip():
                        analysis_summary = json_summary
                    elif ai_response_text.lstrip().startswith("{"):
                        analysis_summary = (
                            "Structured analysis extracted from InBody report."
                        )

                table_data = self._extract_measurements_table(ai_response_text)
                if table_data:
                    analysis_summary = (
                        table_data.get("summary") or analysis_summary
                    )
                    for key, value in table_data.get("metrics", {}).items():
                        extracted_metrics.setdefault(key, value)
                    for key, value in table_data.get("ranges", {}).items():
                        extracted_normal_ranges.setdefault(key, value)

                # Extract actual values using regex patterns
                # Weight extraction
                weight_match = re.search(
                    r"(?<!target\s)weight[:\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if weight_match and "weight" not in extracted_metrics:
                    extracted_metrics["weight"] = (
                        f"{weight_match.group(1)} {weight_match.group(2)}"
                    )
                    normal_range = self._extract_normal_range(
                        ai_response_text,
                        r"\bweight\b",
                        exclude_pattern=r"\btarget\b",
                    )
                    if normal_range and "weight" not in extracted_normal_ranges:
                        extracted_normal_ranges["weight"] = normal_range

                # Target Weight extraction
                target_weight_match = re.search(
                    r"target\s+weight[:\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if (
                    target_weight_match
                    and "target_weight" not in extracted_metrics
                ):
                    extracted_metrics["target_weight"] = (
                        f"{target_weight_match.group(1)} {target_weight_match.group(2)}"
                    )

                # BMI extraction
                bmi_match = re.search(
                    r"bmi[:\s]+([\d.]+)", ai_response_text, re.IGNORECASE
                )
                if bmi_match and "bmi" not in extracted_metrics:
                    extracted_metrics["bmi"] = bmi_match.group(1)
                    normal_range = self._extract_normal_range(
                        ai_response_text, r"\bbmi\b"
                    )
                    if normal_range and "bmi" not in extracted_normal_ranges:
                        extracted_normal_ranges["bmi"] = normal_range

                # Body Fat Percentage extraction
                body_fat_match = re.search(
                    r"(?:percent\s+body\s+fat|body\s+fat(?:\s+percentage)?(?!\s+mass)|pbf)(?:\s*\(.*?\))?[:\-\s]+([\d.]+)\s*%",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if (
                    body_fat_match
                    and "body_fat_percentage" not in extracted_metrics
                ):
                    extracted_metrics["body_fat_percentage"] = (
                        f"{body_fat_match.group(1)}%"
                    )
                    normal_range = self._extract_normal_range(
                        ai_response_text,
                        r"\b(?:pbf|percent\s+body\s+fat|body\s+fat(?:\s+percentage)?)(?!\s+mass)\b",
                    )
                    if (
                        normal_range
                        and "body_fat_percentage"
                        not in extracted_normal_ranges
                    ):
                        extracted_normal_ranges[
                            "body_fat_percentage"
                        ] = normal_range

                # Skeletal Muscle Mass extraction
                muscle_match = re.search(
                    r"(?:skeletal\s+muscle(?:\s+mass)?|muscle\s+mass|smm)(?:\s*\(.*?\))?[:\-\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if (
                    muscle_match
                    and "skeletal_muscle_mass" not in extracted_metrics
                ):
                    extracted_metrics["skeletal_muscle_mass"] = (
                        f"{muscle_match.group(1)} {muscle_match.group(2)}"
                    )
                    normal_range = self._extract_normal_range(
                        ai_response_text,
                        r"\b(?:skeletal\s+muscle(?:\s+mass)?|muscle\s+mass|smm)\b",
                    )
                    if (
                        normal_range
                        and "skeletal_muscle_mass"
                        not in extracted_normal_ranges
                    ):
                        extracted_normal_ranges[
                            "skeletal_muscle_mass"
                        ] = normal_range

                # Body Fat Mass extraction
                body_fat_mass_match = re.search(
                    r"(?:body\s+fat\s+mass|bfm)(?:\s*\(.*?\))?[:\-\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if (
                    body_fat_mass_match
                    and "body_fat_mass" not in extracted_metrics
                ):
                    extracted_metrics["body_fat_mass"] = (
                        f"{body_fat_mass_match.group(1)} {body_fat_mass_match.group(2)}"
                    )
                    normal_range = self._extract_normal_range(
                        ai_response_text, r"\b(?:body\s+fat\s+mass|bfm)\b"
                    )
                    if (
                        normal_range
                        and "body_fat_mass" not in extracted_normal_ranges
                    ):
                        extracted_normal_ranges["body_fat_mass"] = (
                            normal_range
                        )

                # Body Water extraction (percent if provided)
                water_match = re.search(
                    r"body\s+water(?:\s*\(.*?\))?[:\-\s]+([\d.]+)\s*%",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if water_match and "body_water" not in extracted_metrics:
                    extracted_metrics["body_water"] = (
                        f"{water_match.group(1)}%"
                    )
                    normal_range = self._extract_normal_range(
                        ai_response_text,
                        r"\bbody\s+water\b",
                        exclude_pattern=r"\b(?:total|intra|extra)\b",
                    )
                    if (
                        normal_range
                        and "body_water" not in extracted_normal_ranges
                    ):
                        extracted_normal_ranges["body_water"] = normal_range

                # Water Analysis extraction
                total_water_match = re.search(
                    r"(?:total\s+body\s+water|tbw)(?:\s*\(.*?\))?[:\-\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?|l|liters?|litres?)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if (
                    total_water_match
                    and "total_body_water" not in extracted_metrics
                ):
                    extracted_metrics["total_body_water"] = (
                        f"{total_water_match.group(1)} {total_water_match.group(2)}"
                    )
                    normal_range = self._extract_normal_range(
                        ai_response_text,
                        r"\b(?:total\s+body\s+water|tbw)\b",
                    )
                    if (
                        normal_range
                        and "total_body_water"
                        not in extracted_normal_ranges
                    ):
                        extracted_normal_ranges["total_body_water"] = (
                            normal_range
                        )

                intracellular_water_match = re.search(
                    r"(?:intracellular\s+water|icw)(?:\s*\(.*?\))?[:\-\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?|l|liters?|litres?)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if (
                    intracellular_water_match
                    and "intracellular_water" not in extracted_metrics
                ):
                    extracted_metrics["intracellular_water"] = (
                        f"{intracellular_water_match.group(1)} {intracellular_water_match.group(2)}"
                    )
                    normal_range = self._extract_normal_range(
                        ai_response_text,
                        r"\b(?:intracellular\s+water|icw)\b",
                    )
                    if (
                        normal_range
                        and "intracellular_water"
                        not in extracted_normal_ranges
                    ):
                        extracted_normal_ranges["intracellular_water"] = (
                            normal_range
                        )

                extracellular_water_match = re.search(
                    r"(?:extracellular\s+water|ecw)(?:\s*\(.*?\))?[:\-\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?|l|liters?|litres?)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if (
                    extracellular_water_match
                    and "extracellular_water" not in extracted_metrics
                ):
                    extracted_metrics["extracellular_water"] = (
                        f"{extracellular_water_match.group(1)} {extracellular_water_match.group(2)}"
                    )
                    normal_range = self._extract_normal_range(
                        ai_response_text,
                        r"\b(?:extracellular\s+water|ecw)\b",
                    )
                    if (
                        normal_range
                        and "extracellular_water"
                        not in extracted_normal_ranges
                    ):
                        extracted_normal_ranges["extracellular_water"] = (
                            normal_range
                        )

                # Visceral Fat Level extraction
                visceral_match = re.search(
                    r"visceral\s+fat(?:\s+level)?(?:\s*\(.*?\))?[:\-\s]+([\d.]+)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if (
                    visceral_match
                    and "visceral_fat_level" not in extracted_metrics
                ):
                    extracted_metrics["visceral_fat_level"] = visceral_match.group(1)
                    normal_range = self._extract_normal_range(
                        ai_response_text,
                        r"\b(?:visceral\s+fat(?:\s+level)?)\b",
                    )
                    if (
                        normal_range
                        and "visceral_fat_level"
                        not in extracted_normal_ranges
                    ):
                        extracted_normal_ranges[
                            "visceral_fat_level"
                        ] = normal_range

                # Basal Metabolic Rate extraction
                bmr_match = re.search(
                    r"(?:basal\s+metabolic\s+rate|bmr)(?:\s*\(.*?\))?[:\-\s]+([\d.]+)\s*(kcal|calories?)?",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if (
                    bmr_match
                    and "basal_metabolic_rate" not in extracted_metrics
                ):
                    extracted_metrics["basal_metabolic_rate"] = (
                        f"{bmr_match.group(1)} {bmr_match.group(2) if bmr_match.group(2) else 'kcal'}"
                    )
                    normal_range = self._extract_normal_range(
                        ai_response_text,
                        r"\b(?:basal\s+metabolic\s+rate|bmr)\b",
                    )
                    if (
                        normal_range
                        and "basal_metabolic_rate"
                        not in extracted_normal_ranges
                    ):
                        extracted_normal_ranges[
                            "basal_metabolic_rate"
                        ] = normal_range

                # Waist-Hip Ratio extraction
                whr_match = re.search(
                    r"(?:waist[\s-]*hip\s+ratio|whr)(?:\s*\(.*?\))?[:\-\s]+([\d.]+)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if (
                    whr_match
                    and "waist_hip_ratio" not in extracted_metrics
                ):
                    extracted_metrics["waist_hip_ratio"] = whr_match.group(1)
                    normal_range = self._extract_normal_range(
                        ai_response_text,
                        r"\b(?:waist[\s-]*hip\s+ratio|whr)\b",
                    )
                    if (
                        normal_range
                        and "waist_hip_ratio"
                        not in extracted_normal_ranges
                    ):
                        extracted_normal_ranges["waist_hip_ratio"] = (
                            normal_range
                        )

                # Bone Mineral Content extraction
                bone_mineral_match = re.search(
                    r"(?:bone\s+mineral(?:\s+content)?|bmc)(?:\s*\(.*?\))?[:\-\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if (
                    bone_mineral_match
                    and "bone_mineral_content" not in extracted_metrics
                ):
                    extracted_metrics["bone_mineral_content"] = (
                        f"{bone_mineral_match.group(1)} {bone_mineral_match.group(2)}"
                    )
                    normal_range = self._extract_normal_range(
                        ai_response_text,
                        r"\b(?:bone\s+mineral(?:\s+content)?|bmc)\b",
                    )
                    if (
                        normal_range
                        and "bone_mineral_content"
                        not in extracted_normal_ranges
                    ):
                        extracted_normal_ranges["bone_mineral_content"] = (
                            normal_range
                        )

                segmental_metrics = self._extract_segmental_lean_from_text(
                    ai_response_text
                )
                if segmental_metrics:
                    extracted_metrics["segment_lean_analysis"] = [
                        {
                            "label": entry["label"],
                            "value": entry["value"],
                            "unit": entry["unit"],
                        }
                        for entry in segmental_metrics
                    ]
                    for entry in segmental_metrics:
                        key = entry["key"]
                        extracted_metrics[key] = f"{entry['value']} {entry['unit']}"

                # Calculate confidence score based on extracted metrics
                metric_count = len(extracted_metrics)
                if metric_count >= 5:
                    confidence_score = 0.95
                elif metric_count >= 3:
                    confidence_score = 0.85
                elif metric_count >= 1:
                    confidence_score = 0.7
                else:
                    confidence_score = 0.5

                # Extract recommendations from the response
                if "recommend" in ai_response_text.lower():
                    # Try to extract specific recommendations
                    rec_patterns = [
                        r"recommendations?[:\s]*(.*?)(?:\n|$)",
                        r"priority recommendations?[:\s]*(.*?)(?:\n|$)",
                        r"strengths?[:\s]*(.*?)(?:\n|$)",
                        r"areas for improvement[:\s]*(.*?)(?:\n|$)",
                    ]
                    for pattern in rec_patterns:
                        rec_match = re.search(
                            pattern,
                            ai_response_text,
                            re.IGNORECASE | re.DOTALL,
                        )
                        if rec_match:
                            rec_text = rec_match.group(1).strip()
                            if rec_text and len(rec_text) > 10:
                                recommendations.append(rec_text[:200])
                                break

                    if not recommendations:
                        recommendations.append(
                            "Follow the personalized recommendations provided in the analysis"
                        )

                # Extract risk factors
                if (
                    "risk" in ai_response_text.lower()
                    or "concern" in ai_response_text.lower()
                    or "abnormal" in ai_response_text.lower()
                ):
                    risk_patterns = [
                        r"risk factors?[:\s]*(.*?)(?:\n|$)",
                        r"concerns?[:\s]*(.*?)(?:\n|$)",
                        r"abnormal[:\s]*(.*?)(?:\n|$)",
                    ]
                    for pattern in risk_patterns:
                        risk_match = re.search(
                            pattern,
                            ai_response_text,
                            re.IGNORECASE | re.DOTALL,
                        )
                        if risk_match:
                            risk_text = risk_match.group(1).strip()
                            if risk_text and len(risk_text) > 10:
                                risk_factors.append(risk_text[:200])
                                break

                    if not risk_factors:
                        risk_factors.append(
                            "Review identified concerns with healthcare provider"
                        )

                ai_response = {
                    "response": analysis_summary,
                    "metadata": {
                        "confidence_score": confidence_score,
                        "extracted_metrics": extracted_metrics,
                        "extracted_normal_ranges": extracted_normal_ranges,
                        "recommendations": recommendations,
                        "risk_factors": risk_factors,
                    },
                }

            except Exception as ai_error:
                print(f"Vision analysis failed: {str(ai_error)}")
                # Provide fallback response
                ai_response = {
                    "response": f"File '{file_name}' has been uploaded successfully. AI vision analysis is currently unavailable, but the report has been stored for future processing.",
                    "metadata": {
                        "confidence_score": 0.0,
                        "extracted_metrics": {},
                        "extracted_normal_ranges": {},
                    },
                }

            normalized_payload = self._build_normalized_inbody_payload(
                ai_response.get("metadata", {}).get("extracted_metrics", {}),
                ai_response.get("metadata", {}).get("confidence_score", 0.0),
                file_name=file_name,
                content_type=content_type,
            )

            # Return AI response immediately without storing in database yet
            analysis_result = InbodyReportAnalysisResult(
                file_name=file_name,
                processed_at=datetime.now().isoformat(),
                ai_analysis={
                    "summary": ai_response.get(
                        "response",
                        "Analysis completed but no detailed response available.",
                    ),
                    "confidence_score": ai_response.get("metadata", {}).get(
                        "confidence_score", 0.0
                    ),
                    "extracted_metrics": ai_response.get("metadata", {}).get(
                        "extracted_metrics", {}
                    ),
                    "extracted_normal_ranges": ai_response.get("metadata", {}).get(
                        "extracted_normal_ranges", {}
                    ),
                    "recommendations": ai_response.get("metadata", {}).get(
                        "recommendations", []
                    ),
                    "risk_factors": ai_response.get("metadata", {}).get(
                        "risk_factors", []
                    ),
                    "structured": (
                        True
                        if ai_response.get("metadata", {}).get(
                            "confidence_score", 0.0
                        )
                        > 0
                        else False
                    ),
                },
                values=normalized_payload["values"],
                derived=normalized_payload["derived"],
                parse_confidence=normalized_payload["parse_confidence"],
                confirmation_needed=normalized_payload["confirmation_needed"],
                provenance=normalized_payload["provenance"],
                metadata={
                    "content_type": content_type,
                    "file_size": len(file_content),
                    "enrollment_id": str(enrollment_id),
                    "original_filename": file_name,
                    "ready_for_storage": True,
                },
            )

            print(
                f"Base64 processing workflow completed. Analysis result prepared with file: {analysis_result.file_name}"
            )

            # Step 5: Store the analyzed report in database
            print("Step 5: Storing analyzed report in database...")
            try:
                from lib.schemas.weight_loss_agent import InbodyReportCreate

                # Create report data from analysis result
                report_data = InbodyReportCreate(
                    report_date=datetime.now(),
                    ai_summary=analysis_result.ai_analysis.get("summary"),
                    original_filename=analysis_result.file_name,
                    file_size=analysis_result.metadata.get("file_size", 0),
                    content_type=analysis_result.metadata.get(
                        "content_type", ""
                    ),
                )

                # Store the report in database
                report = await self.create_inbody_report(
                    enrollment_id, report_data
                )
                report_id = report["report_id"]
                print(f"Report stored in database with ID: {report_id}")

                # Step 6: Create measurements and health indicators from extracted metrics
                print(
                    "Step 6: Storing extracted measurements and health indicators..."
                )

                # Get extracted metrics from AI response
                extracted_metrics = analysis_result.ai_analysis.get(
                    "extracted_metrics", {}
                )
                extracted_normal_ranges = analysis_result.ai_analysis.get(
                    "extracted_normal_ranges", {}
                )
                confidence_score = analysis_result.ai_analysis.get(
                    "confidence_score", 0.0
                )

                # Create measurement documents
                measurements = []
                measurements_created = 0

                # Persist segmental lean measurements separately so they can be surfaced in highlights
                segmental_entries = (
                    extracted_metrics.get("segment_lean_analysis") or []
                )
                for entry in segmental_entries:
                    try:
                        label = entry.get("label")
                        value = entry.get("value")
                        if label is None or value is None:
                            continue

                        value_number = float(value)
                        unit = entry.get("unit") or "kg"

                        measurements.append(
                            {
                                "measurement_type": label,
                                "value": value_number,
                                "unit": unit,
                                "confidence_score": confidence_score,
                            }
                        )
                        measurements_created += 1
                        print(
                            f"  - Created segmental lean measurement: {label} = {value_number} {unit}"
                        )
                    except (TypeError, ValueError) as segment_error:
                        print(
                            f"  - Failed to create segmental lean measurement: {str(segment_error)}"
                        )

                metric_label_overrides = {
                    "skeletal_muscle_mass": "Skeletal Muscle Mass",
                    "muscle_mass": "Skeletal Muscle Mass",
                    "body_fat_percentage": "Body Fat Percentage",
                    "percentage_body_fat": "Body Fat Percentage",
                    "body_fat": "Body Fat Percentage",
                    "body_fat_mass": "Body Fat Mass",
                    "waist_hip_ratio": "Waist-Hip Ratio",
                    "visceral_fat_level": "Visceral Fat Level",
                    "visceral_fat": "Visceral Fat Level",
                    "basal_metabolic_rate": "Basal Metabolic Rate",
                    "bmr": "Basal Metabolic Rate",
                    "bone_mineral_content": "Bone Mineral Content",
                    "total_body_water": "Total Body Water",
                    "intracellular_water": "Intracellular Water",
                    "extracellular_water": "Extracellular Water",
                }

                for metric_name, metric_value in extracted_metrics.items():
                    try:
                        if (
                            isinstance(metric_value, (list, dict))
                            or metric_name == "segment_lean_analysis"
                            or metric_name.startswith("segment_")
                        ):
                            continue

                        # Parse the value and unit
                        metric_value_str = str(metric_value)

                        value_match = re.search(
                            r"([\d.]+)", str(metric_value_str)
                        )
                        if value_match:
                            value = float(value_match.group(1))
                            metric_name_lower = metric_name.lower()

                            # Extract unit (everything after the number)
                            unit = (
                                str(metric_value_str)
                                .replace(value_match.group(1), "")
                                .strip()
                            )
                            if not unit:
                                # Default units based on metric type
                                if "visceral_fat" in metric_name_lower:
                                    unit = "level"
                                elif "fat_mass" in metric_name_lower:
                                    unit = "kg"
                                elif "bone_mineral" in metric_name_lower:
                                    unit = "kg"
                                elif metric_name_lower in [
                                    "total_body_water",
                                    "intracellular_water",
                                    "extracellular_water",
                                ]:
                                    unit = "L"
                                elif "weight" in metric_name_lower:
                                    unit = "kg"
                                elif "bmi" in metric_name_lower:
                                    unit = ""
                                elif (
                                    "fat" in metric_name_lower
                                    or "water" in metric_name_lower
                                ):
                                    unit = "%"
                                elif (
                                    "rate" in metric_name_lower
                                    or "bmr" in metric_name_lower
                                ):
                                    unit = "kcal"
                                else:
                                    unit = ""

                            normal_min = None
                            normal_max = None
                            range_value = extracted_normal_ranges.get(metric_name)
                            if range_value:
                                parsed_range = self._parse_normal_range(
                                    range_value
                                )
                                if parsed_range:
                                    normal_min, normal_max = parsed_range

                            # Create measurement document
                            measurement = {
                                "measurement_type": metric_label_overrides.get(
                                    metric_name,
                                    metric_name.replace("_", " ").title(),
                                ),
                                "value": value,
                                "unit": unit,
                                "normal_min": normal_min,
                                "normal_max": normal_max,
                                "confidence_score": confidence_score,
                            }
                            measurements.append(measurement)
                            measurements_created += 1
                            print(
                                f"  - Created measurement: {metric_name} = {value} {unit}"
                            )
                    except Exception as metric_error:
                        print(
                            f"  - Failed to create measurement for {metric_name}: {str(metric_error)}"
                        )

                # Create health indicators for abnormal values
                health_indicators = []
                indicators_created = 0
                for measurement in measurements:
                    try:
                        normal_min = measurement.get("normal_min")
                        normal_max = measurement.get("normal_max")
                        value = measurement.get("value")
                        if (
                            normal_min is None
                            or normal_max is None
                            or value is None
                        ):
                            continue

                        abnormality_level = self._get_abnormality_level(
                            value, normal_min, normal_max
                        )
                        if not abnormality_level:
                            continue

                        measurement_type = measurement.get(
                            "measurement_type", "Measurement"
                        )
                        unit = measurement.get("unit", "")
                        indicator_name = (
                            f"{abnormality_level.title()} {measurement_type}"
                        )
                        range_label = f"{normal_min}-{normal_max}"
                        unit_label = f" {unit}" if unit else ""

                        indicator = {
                            "indicator_name": indicator_name,
                            "indicator_type": "warning",
                            "value": value,
                            "unit": unit,
                            "is_abnormal": True,
                            "abnormality_level": abnormality_level,
                            "normal_range_min": normal_min,
                            "normal_range_max": normal_max,
                            "analysis_explanation": (
                                f"{measurement_type} of {value}{unit_label} is "
                                f"{abnormality_level} compared to normal range {range_label}."
                            ),
                            "recommendations": "Discuss this result with a healthcare provider for personalized guidance.",
                        }
                        health_indicators.append(indicator)
                        indicators_created += 1
                        print(
                            f"  - Created indicator: {indicator_name} ({value}{unit_label})"
                        )
                    except Exception as indicator_error:
                        print(
                            f"  - Failed to process indicator: {str(indicator_error)}"
                        )

                # Update the report with measurements and indicators in MongoDB
                await self.reports_collection.update_one(
                    {"report_id": report_id},
                    {
                        "$set": {
                            "measurements": measurements,
                            "health_indicators": health_indicators,
                            "ai_summary": analysis_result.ai_analysis.get(
                                "summary"
                            ),
                            "processed": True,
                            "measurements_count": measurements_created,
                            "abnormal_indicators_count": indicators_created,
                            "extraction_confidence": confidence_score,
                            "updated_at": datetime.now(),
                        }
                    },
                )
                print(
                    f"Successfully stored {measurements_created} measurements and {indicators_created} health indicators"
                )

                # Update the analysis result with the report ID and storage info
                analysis_result.report_id = report_id
                analysis_result.stored_at = datetime.now().isoformat()
                analysis_result.metadata["stored"] = True
                analysis_result.metadata["measurements_created"] = (
                    measurements_created
                )
                analysis_result.metadata["indicators_created"] = (
                    indicators_created
                )
                analysis_result.metadata["ai_summary_pending"] = True

                print(
                    "Report successfully stored in database with measurements and health indicators"
                )
                return analysis_result

            except Exception as storage_error:
                print(
                    f"Failed to store report in database: {str(storage_error)}"
                )
                # Still return the analysis result even if storage fails
                analysis_result.metadata["storage_error"] = str(storage_error)
                analysis_result.metadata["stored"] = False
                return analysis_result

        except Exception as e:
            print(f"Error in process_and_analyze_inbody_report: {str(e)}")
            import traceback

            traceback.print_exc()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"Failed to process inbody report: {str(e)}",
            )
