"""Unit tests for InbodyTextReprBuilder."""

from lib.services.vector.inbody.text_builder import InbodyTextReprBuilder

ANALYSIS = {
    "inbody_score": 61,
    "device_model": "InBody 770",
    "measurements": [
        {
            "name": "weight",
            "value": 74.4,
            "unit": "kg",
            "normal_range_low": 49.0,
            "normal_range_high": 66.4,
            "level": "high",
        },
        {
            "name": "skeletal_muscle_mass",
            "value": 26.7,
            "unit": "kg",
            "level": "normal",
        },
    ],
    "weight_control": {
        "target_weight_kg": 57.7,
        "weight_control_kg": -16.7,
        "fat_control_kg": -18.1,
        "muscle_control_kg": 1.4,
    },
    "nutrition_evaluation": {
        "protein": "normal",
        "body_fat": "over",
        "summary": None,
    },
    "obesity_evaluation": {"bmi": "over", "percent_body_fat": "over"},
    "body_balance_evaluation": {"upper": "balanced", "lower": "balanced"},
    "segmental_lean": [
        {
            "segment": "right_arm",
            "mass_kg": 2.65,
            "percent_of_normal": 89.7,
            "level": "low",
        },
        {
            "segment": "trunk",
            "mass_kg": 22.1,
            "percent_of_normal": 93.8,
            "level": "normal",
        },
    ],
    "segmental_fat": [],
    "impedance_note": "Readings look consistent across segments.",
}


class TestBuild:
    def test_contains_core_facts(self):
        text = InbodyTextReprBuilder.build(ANALYSIS, "2026-01-10")
        assert "2026-01-10" in text
        assert "InBody 770" in text
        assert "InBody score: 61/100" in text
        assert "weight: 74.4 kg (normal 49.0-66.4) [high]" in text
        assert "skeletal muscle mass: 26.7 kg" in text
        assert "target weight 57.7 kg" in text
        assert "recommended fat change -18.1 kg" in text

    def test_evaluation_sections(self):
        text = InbodyTextReprBuilder.build(ANALYSIS, "2026-01-10")
        assert "Nutritional evaluation" in text
        assert "body fat: over" in text
        assert "Obesity evaluation" in text
        assert "Body balance" in text

    def test_segmental_only_out_of_range(self):
        text = InbodyTextReprBuilder.build(ANALYSIS, "2026-01-10")
        assert "right arm low (89.7% of ideal)" in text
        # trunk is normal — must not appear in the out-of-range narrative
        assert "trunk" not in text

    def test_needs_review_note(self):
        flagged = InbodyTextReprBuilder.build(
            ANALYSIS, "2026-01-10", needs_review=True
        )
        clean = InbodyTextReprBuilder.build(ANALYSIS, "2026-01-10")
        assert "Low extraction confidence" in flagged
        assert "Low extraction confidence" not in clean

    def test_impedance_note(self):
        text = InbodyTextReprBuilder.build(ANALYSIS, "2026-01-10")
        assert "Readings look consistent" in text

    def test_minimal_analysis(self):
        text = InbodyTextReprBuilder.build({}, None)
        assert "unknown date" in text
        assert text.endswith(".")
