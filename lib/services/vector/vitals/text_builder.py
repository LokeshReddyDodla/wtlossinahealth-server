"""Text representation builder for patient vitals data."""

from datetime import datetime
from typing import Any, Dict


class VitalsTextReprBuilder:
    """Builder for creating text representations of patient vitals."""

    @staticmethod
    def build(vital: Dict[str, Any]) -> str:
        """
        Build text representation for a vital reading.

        Args:
            vital: Vital data dictionary

        Returns:
            Text representation string
        """
        text_parts = []

        # Parse test time
        test_time = vital.get("test_time")
        dt = None
        if isinstance(test_time, datetime):
            dt = test_time
        elif isinstance(test_time, str):
            try:
                dt = datetime.fromisoformat(str(test_time).replace("Z", "+00:00"))
            except Exception:
                pass

        date_str = dt.strftime("%Y-%m-%d") if dt else "unknown date"
        time_str = dt.strftime("%H:%M") if dt else "unknown time"

        # Build vital measurements
        vital_measurements = []

        # Blood pressure
        systolic = vital.get("systolic_bp")
        diastolic = vital.get("diastolic_bp")
        if systolic is not None and diastolic is not None:
            vital_measurements.append(f"Blood pressure: {systolic}/{diastolic} mmHg")

        # Heart rate
        heart_rate = vital.get("heart_rate")
        if heart_rate is not None:
            vital_measurements.append(f"Heart rate: {heart_rate} bpm")

        # Resting heart rate
        resting_heart_rate = vital.get("resting_heart_rate")
        if resting_heart_rate is not None:
            vital_measurements.append(f"Resting heart rate: {resting_heart_rate} bpm")

        # Temperature
        temperature = vital.get("temperature")
        if temperature is not None:
            vital_measurements.append(f"Temperature: {temperature}°C")

        # SpO2 (Oxygen saturation)
        spo2 = vital.get("spo2")
        if spo2 is not None:
            vital_measurements.append(f"Oxygen saturation (SpO2): {spo2}%")

        # Respiratory rate
        respiratory_rate = vital.get("respiratory_rate")
        if respiratory_rate is not None:
            vital_measurements.append(f"Respiratory rate: {respiratory_rate} breaths/min")

        # Weight
        weight = vital.get("weight")
        if weight is not None:
            vital_measurements.append(f"Weight: {weight} kg")

        # A1C (HbA1c)
        a1c = vital.get("a1c")
        if a1c is not None:
            vital_measurements.append(f"HbA1c: {a1c}%")

        # Creatinine
        creatinine = vital.get("creatinine")
        if creatinine is not None:
            vital_measurements.append(f"Creatinine: {creatinine} mg/dL")

        # Ketones
        ketones = vital.get("ketones")
        if ketones is not None:
            vital_measurements.append(f"Ketones: {ketones} mmol/L")

        # Build text parts
        text_parts.append(f"Vital signs recorded on {date_str} at {time_str}.")

        if vital_measurements:
            text_parts.append("Measurements: " + ", ".join(vital_measurements) + ".")

        # Add source information
        source_name = vital.get("source_name", "")
        source_platform = vital.get("source_platform", "")
        if source_name or source_platform:
            source_info = []
            if source_name:
                source_info.append(f"source: {source_name}")
            if source_platform:
                source_info.append(f"platform: {source_platform}")
            text_parts.append("Recorded via " + ", ".join(source_info) + ".")

        # Add health interpretation
        interpretation = VitalsTextReprBuilder._interpret_vitals(vital)
        if interpretation:
            text_parts.append(interpretation)

        return " ".join(text_parts)

    @staticmethod
    def _interpret_vitals(vital: Dict[str, Any]) -> str:
        """
        Generate health-related interpretation for embedding context.

        Args:
            vital: Vital data dictionary

        Returns:
            Interpretation string
        """
        interpretations = []

        # Blood pressure interpretation
        systolic = vital.get("systolic_bp")
        diastolic = vital.get("diastolic_bp")
        if systolic is not None and diastolic is not None:
            if systolic >= 140 or diastolic >= 90:
                interpretations.append("elevated blood pressure")
            elif systolic < 90 or diastolic < 60:
                interpretations.append("low blood pressure")
            else:
                interpretations.append("normal blood pressure")

        # Heart rate interpretation
        heart_rate = vital.get("heart_rate")
        if heart_rate is not None:
            if heart_rate > 100:
                interpretations.append("elevated heart rate (tachycardia)")
            elif heart_rate < 60:
                interpretations.append("low heart rate (bradycardia)")
            else:
                interpretations.append("normal heart rate")

        # SpO2 interpretation
        spo2 = vital.get("spo2")
        if spo2 is not None:
            if spo2 < 95:
                interpretations.append("low oxygen saturation")
            else:
                interpretations.append("normal oxygen saturation")

        # Temperature interpretation
        temperature = vital.get("temperature")
        if temperature is not None:
            if temperature > 37.5:
                interpretations.append("elevated temperature (fever)")
            elif temperature < 36.0:
                interpretations.append("low temperature (hypothermia)")
            else:
                interpretations.append("normal temperature")

        # A1C interpretation
        a1c = vital.get("a1c")
        if a1c is not None:
            if a1c >= 6.5:
                interpretations.append("elevated HbA1c (diabetes range)")
            elif a1c >= 5.7:
                interpretations.append("elevated HbA1c (prediabetes range)")
            else:
                interpretations.append("normal HbA1c")

        if interpretations:
            return f"Health status: {', '.join(interpretations)}."
        return ""
