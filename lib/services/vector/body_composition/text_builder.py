"""Text representation builder for body-composition scans."""

from typing import Any, Dict

from lib.services.body_composition.metrics import SPEC_BY_KEY

# Metrics surfaced in the embedded text, in reading order — device-neutral.
_SUMMARY_KEYS = (
    "weight",
    "skeletal_muscle_mass",
    "body_fat_mass",
    "percent_body_fat",
    "bmi",
    "visceral_fat_level",
    "basal_metabolic_rate",
    "ecw_tbw_ratio",
    "whole_body_phase_angle",
    "skeletal_muscle_index",
    "waist_hip_ratio",
    "total_body_water",
)

_REGION_LABEL = {
    "right_arm": "right arm",
    "left_arm": "left arm",
    "trunk": "trunk",
    "right_leg": "right leg",
    "left_leg": "left leg",
}


class BodyCompositionTextReprBuilder:
    """Builds the text embedded for a body-composition scan."""

    @staticmethod
    def build(record: Dict[str, Any]) -> str:
        metrics = record.get("metrics") or {}
        date_str = str(record.get("test_datetime") or "")[:10] or "unknown date"
        device = " ".join(
            p for p in (record.get("manufacturer"), record.get("device_model")) if p
        )
        method = (record.get("measurement_method") or "").upper()

        head = f"Body composition scan on {date_str}"
        if device:
            head += f" ({device}"
            head += f", {method})." if method else ")."
        else:
            head += "."

        parts = [head]
        for key in _SUMMARY_KEYS:
            value = metrics.get(key)
            if value is None:
                continue
            spec = SPEC_BY_KEY.get(key)
            unit = f" {spec.unit}" if spec and spec.unit else ""
            parts.append(f"{key.replace('_', ' ').capitalize()}: {value}{unit}.")

        segmental = (record.get("data") or {}).get("segmental") or []
        seg_bits = []
        for s in segmental:
            pct = s.get("lean_percent_reference")
            region = _REGION_LABEL.get(s.get("region"), s.get("region"))
            if pct is not None:
                seg_bits.append(f"{region} {round(pct)}% of ideal")
        if seg_bits:
            parts.append("Segmental lean: " + ", ".join(seg_bits) + ".")

        return " ".join(parts)
