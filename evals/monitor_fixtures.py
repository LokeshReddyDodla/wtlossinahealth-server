"""Fixture scenarios for proactive-monitor evals.

Each scenario builds records for "today" in a timezone chosen at runtime so
the monitor's scan period is deterministic (never the morning/daily-brief
path): we pick a tz where local time is currently afternoon or evening.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

# Spread of timezones ~2h apart — one of them is always mid-afternoon.
_TZ_CANDIDATES = [
    "Asia/Kolkata", "Asia/Dubai", "Asia/Tokyo", "Asia/Shanghai",
    "Europe/London", "Europe/Berlin", "Europe/Moscow",
    "America/New_York", "America/Chicago", "America/Los_Angeles",
    "Australia/Sydney", "Pacific/Auckland",
]


def pick_afternoon_timezone() -> str:
    """A timezone where it is currently 13:00-16:59 local.

    Keeps the monitor on the ScanInsights path ("today so far") — the
    morning path collapses to a DailyBrief, a different output contract.
    """
    for tz in _TZ_CANDIDATES:
        if 13 <= datetime.now(ZoneInfo(tz)).hour < 17:
            return tz
    # Fallback: widest non-morning window (12:00-21:59)
    for tz in _TZ_CANDIDATES:
        if 12 <= datetime.now(ZoneInfo(tz)).hour < 22:
            return tz
    return "Asia/Kolkata"  # pragma: no cover — candidates span the globe


def _today(tz_name: str, hour: int) -> datetime:
    now = datetime.now(ZoneInfo(tz_name))
    return now.replace(hour=min(hour, max(now.hour - 1, 0)), minute=0, second=0, microsecond=0)


def _ms(dt: datetime) -> float:
    return dt.timestamp() * 1000


def _base_profile(tz_name: str) -> list[dict[str, Any]]:
    now = datetime.now(ZoneInfo(tz_name))
    return [{
        "data_type": "profile",
        "start_time": _ms(now - timedelta(days=365)),
        "end_time": _ms(now),
        "text_repr": (
            "Patient profile: Asha, 42-year-old female, type 2 diabetes "
            "diagnosed 2022, on Metformin 500mg twice daily."
        ),
        "name": "Asha", "age": 42, "gender": "female",
        "condition": "type 2 diabetes (2022)", "medications": "Metformin 500mg twice daily",
    }]


def scenario_normal_day(tz_name: str) -> list[dict[str, Any]]:
    """Boring, healthy day — the monitor should NOT raise concerns."""
    d = _today(tz_name, 6)
    return _base_profile(tz_name) + [
        {
            "data_type": "cgm_summary_stats",
            "start_time": _ms(d),
            "end_time": _ms(d),
            "text_repr": (
                f"CGM summary for {d.date().isoformat()} so far: average glucose "
                f"118 mg/dL, time in range 94%, no highs, no lows, very stable."
            ),
            "average_glucose": 118, "time_in_range_pct": 94,
            "hypo_events": 0, "hyper_events": 0, "glucose_variability": "low",
        },
        {
            "data_type": "meal",
            "start_time": _ms(_today(tz_name, 8)),
            "end_time": _ms(_today(tz_name, 8)),
            "text_repr": (
                f"Meal on {d.date().isoformat()} 8:00 AM (breakfast): vegetable "
                f"omelette with one roti — approx 320 kcal, 28g carbs, 18g protein."
            ),
            "meal_type": "breakfast", "description": "vegetable omelette with one roti",
            "calories": 320, "carbs_g": 28, "protein_g": 18, "meal_time": "8:00 AM",
        },
        {
            "data_type": "fitness_overview",
            "start_time": _ms(d),
            "end_time": _ms(d),
            "text_repr": (
                f"Fitness overview for {d.date().isoformat()}: 8,200 steps so far, "
                f"35 active minutes."
            ),
            "steps": 8200, "active_minutes": 35,
        },
    ]


def scenario_hypo_today(tz_name: str) -> list[dict[str, Any]]:
    """A real hypo this morning — the monitor MUST flag it, high severity."""
    d = _today(tz_name, 6)
    return _base_profile(tz_name) + [
        {
            "data_type": "hypo_event",
            "start_time": _ms(_today(tz_name, 5)),
            "end_time": _ms(_today(tz_name, 5)),
            "text_repr": (
                f"Hypoglycemia event on {d.date().isoformat()} at 5:10 AM: glucose "
                f"dropped to 51 mg/dL for 40 minutes while asleep."
            ),
            "lowest_glucose": 51, "duration_minutes": 40,
            "event_time": "5:10 AM", "context": "overnight, while asleep",
        },
        {
            "data_type": "cgm_summary_stats",
            "start_time": _ms(d),
            "end_time": _ms(d),
            "text_repr": (
                f"CGM summary for {d.date().isoformat()} so far: average glucose "
                f"112 mg/dL, time in range 81%, one hypoglycemia episode overnight."
            ),
            "average_glucose": 112, "time_in_range_pct": 81, "hypo_events": 1,
        },
    ]


def scenario_spike_after_meal(tz_name: str) -> list[dict[str, Any]]:
    """Large post-meal spike — expect a meal-linked insight, not panic."""
    d = _today(tz_name, 6)
    return _base_profile(tz_name) + [
        {
            "data_type": "meal",
            "start_time": _ms(_today(tz_name, 9)),
            "end_time": _ms(_today(tz_name, 9)),
            "text_repr": (
                f"Meal on {d.date().isoformat()} 9:00 AM (breakfast): aloo paratha "
                f"with pickle — approx 540 kcal, 88g carbs, 11g protein."
            ),
            "meal_type": "breakfast", "description": "aloo paratha with pickle",
            "calories": 540, "carbs_g": 88, "protein_g": 11, "meal_time": "9:00 AM",
        },
        {
            "data_type": "rapid_spike_event",
            "start_time": _ms(_today(tz_name, 10)),
            "end_time": _ms(_today(tz_name, 10)),
            "text_repr": (
                f"Rapid glucose spike on {d.date().isoformat()} at 9:50 AM: rose "
                f"from 124 to 228 mg/dL in 50 minutes, shortly after breakfast."
            ),
            "from_glucose": 124, "to_glucose": 228, "duration_minutes": 50,
            "event_time": "9:50 AM", "context": "shortly after breakfast",
        },
        {
            "data_type": "cgm_summary_stats",
            "start_time": _ms(d),
            "end_time": _ms(d),
            "text_repr": (
                f"CGM summary for {d.date().isoformat()} so far: average glucose "
                f"142 mg/dL, time in range 74%, one rapid spike mid-morning."
            ),
            "average_glucose": 142, "time_in_range_pct": 74, "rapid_spikes": 1,
        },
    ]


SCENARIOS = {
    "normal_day": scenario_normal_day,
    "hypo_today": scenario_hypo_today,
    "spike_after_meal": scenario_spike_after_meal,
    "empty": lambda tz: [],
}
