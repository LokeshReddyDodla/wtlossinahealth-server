"""Text-repr test for the sleep vector builder."""

from lib.services.vector.sleep.text_builder import build_sleep_text


def test_build_sleep_text_covers_stages_quality_trend():
    report = {
        "duration": {"total_duration": 465},
        "type_distribution": {
            "distribution": {
                "sleep_deep": {"total_duration": 90},
                "sleep_rem": {"total_duration": 105},
                "sleep_light": {"total_duration": 255},
                "sleep_awake": {"total_duration": 15},
            }
        },
        "quality": {
            "sleep_efficiency": 88.0, "restorative_sleep": 42.0,
            "sleep_quality": "good", "average_awakenings": 3.0,
            "average_waso_minutes": 22.0,
        },
        "timing": {"average_start_time": "23:40", "average_end_time": "07:25"},
        "consistency": {"consistency_score": 74.0, "sleep_debt_minutes": 30.0,
                        "subjective_quality": 4.0},
        "trend": {"delta_average_sleep_minutes": -25.0, "delta_efficiency": -3.0},
    }
    text = build_sleep_text("2026-08-18T00:00:00", "2026-08-18T23:59:59", report)

    assert "total asleep 7h45m" in text
    assert "deep 1h30m" in text and "rem 1h45m" in text
    assert "efficiency 88.0%" in text and "quality good" in text
    assert "consistency score 74.0/100" in text
    assert "-25 min sleep" in text


def test_build_sleep_text_handles_empty_stages():
    text = build_sleep_text("s", "e", {"duration": {"total_duration": 400}})
    assert "total asleep 6h40m" in text
    assert "deep n/a" in text
