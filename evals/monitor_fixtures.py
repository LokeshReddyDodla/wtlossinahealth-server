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


def scenario_weight_loss_no_cgm(tz_name: str) -> list[dict[str, Any]]:
    """Weight-loss patient, NO glucose data at all — insights must stay
    in the domains that exist (meals, fitness, weight)."""
    d = _today(tz_name, 6)
    now = datetime.now(ZoneInfo(tz_name))
    return [
        {
            "data_type": "profile",
            "start_time": _ms(now - timedelta(days=365)),
            "end_time": _ms(now),
            "text_repr": (
                "Patient profile: Rohan, 35-year-old male, no chronic "
                "conditions, goal: lose 8 kg, no medications."
            ),
            "name": "Rohan", "age": 35, "gender": "male",
            "condition": "none", "health_goal": "lose 8 kg",
        },
        {
            "data_type": "meal",
            "start_time": _ms(_today(tz_name, 8)),
            "end_time": _ms(_today(tz_name, 8)),
            "text_repr": (
                f"Meal on {d.date().isoformat()} 8:00 AM (breakfast): oats with "
                f"whey protein and banana — approx 420 kcal, 52g carbs, 34g protein."
            ),
            "meal_type": "breakfast", "description": "oats with whey protein and banana",
            "calories": 420, "carbs_g": 52, "protein_g": 34, "meal_time": "8:00 AM",
        },
        {
            "data_type": "fitness_overview",
            "start_time": _ms(d),
            "end_time": _ms(d),
            "text_repr": (
                f"Fitness overview for {d.date().isoformat()}: 9,400 steps so far, "
                f"42 active minutes, one 25-minute strength session."
            ),
            "steps": 9400, "active_minutes": 42, "workouts": "25-min strength session",
        },
        {
            "data_type": "vital",
            "start_time": _ms(d),
            "end_time": _ms(d),
            "text_repr": f"Vitals on {d.date().isoformat()}: weight 82.9 kg (down 1.3 kg over 3 weeks).",
            "weight_kg": 82.9, "weight_trend": "down 1.3 kg over 3 weeks",
        },
    ]


# -- Dietitian-feedback scenarios (clinical review of 30/06/2026) -------------
# Each reproduces a real flagged notification; the dietitian's correction is
# the pass/fail bar in the golden suite. Event-mode cases carry meal_id so
# the executor can anchor a meal_logged trigger on them.


def scenario_fiber_overcredit_meal(tz_name: str) -> list[dict[str, Any]]:
    """Real case: lunch praised as 'hit the mark for protein and fiber' when
    fiber was actually lacking. The numbers say 3g fiber — no fiber credit."""
    d = _today(tz_name, 6)
    return _base_profile(tz_name) + [
        {
            "data_type": "meal",
            "meal_id": "meal-fiber-overcredit",
            "start_time": _ms(_today(tz_name, 13)),
            "end_time": _ms(_today(tz_name, 13)),
            "text_repr": (
                f"Meal on {d.date().isoformat()} 1:00 PM (lunch): 2 chapati with "
                f"chicken curry and a few cucumber slices — approx 520 kcal, "
                f"48g carbs, 32g protein, 3g fiber."
            ),
            "meal_type": "lunch",
            "description": "2 chapati with chicken curry and a few cucumber slices",
            "calories": 520, "carbs_g": 48, "protein_g": 32, "fiber_g": 3,
            "meal_time": "1:00 PM",
        },
        {
            "data_type": "cgm_summary_stats",
            "start_time": _ms(d),
            "end_time": _ms(d),
            "text_repr": (
                f"CGM summary for {d.date().isoformat()} so far: average glucose "
                f"126 mg/dL, time in range 85%, no highs, no lows."
            ),
            "average_glucose": 126, "time_in_range_pct": 85,
            "hypo_events": 0, "hyper_events": 0,
        },
    ]


def scenario_carb_meal_fiber_gap(tz_name: str) -> list[dict[str, Any]]:
    """Real case: upma breakfast — insight said 'pair carbs with protein' but
    never mentioned fiber, the other missing lever for a high-carb meal."""
    d = _today(tz_name, 6)
    return _base_profile(tz_name) + [
        {
            "data_type": "meal",
            "meal_id": "meal-upma-breakfast",
            "start_time": _ms(_today(tz_name, 9)),
            "end_time": _ms(_today(tz_name, 9)),
            "text_repr": (
                f"Meal on {d.date().isoformat()} 9:00 AM (breakfast): plain rava "
                f"upma — approx 380 kcal, 62g carbs, 7g protein, 2g fiber."
            ),
            "meal_type": "breakfast", "description": "plain rava upma",
            "calories": 380, "carbs_g": 62, "protein_g": 7, "fiber_g": 2,
            "meal_time": "9:00 AM",
        },
    ]


def scenario_meal_items_need_aggregation(tz_name: str) -> list[dict[str, Any]]:
    """Real case: patient logged one meal as 6 separate items; each item got
    praised individually ('light choice') while the aggregate was high in
    calories and carbs. Anchor = the salad (the item that got the praise)."""
    # The sitting ends 45 min before "now" — a meal_logged trigger fires right
    # after logging, so relative anchoring is realistic AND immune to the
    # wall-clock hour of the eval run. Absolute/clamped hours made this case
    # hour-sensitive: at early-local-hours CI runs the clamp produced a
    # "dinner" at ~2 PM and the LLM (correctly, per its no-nagging rule)
    # declined to comment on an incoherent borderline meal.
    now = datetime.now(ZoneInfo(tz_name))
    d = now
    h = now - timedelta(minutes=45)
    # pick_afternoon_timezone guarantees local hour ∈ [12, 22): sitting lands
    # 11:15-21:15 → lunch before 5 PM, dinner after.
    sitting_meal_type = "lunch" if h.hour < 17 else "dinner"

    def item(mins_ago: int, mid: str, desc: str, cal: int, carb: int, prot: int, fib: int):
        t = h - timedelta(minutes=mins_ago)
        return {
            "data_type": "meal",
            "meal_id": mid,
            "start_time": _ms(t), "end_time": _ms(t),
            "text_repr": (
                f"Meal on {d.date().isoformat()} (logged with other items, same "
                f"meal): {desc} — approx {cal} kcal, {carb}g carbs, {prot}g "
                f"protein, {fib}g fiber."
            ),
            "meal_type": sitting_meal_type, "description": desc,
            "calories": cal, "carbs_g": carb, "protein_g": prot, "fiber_g": fib,
        }

    # The earlier meal stays well OUTSIDE the 90-min sitting window at any
    # wall-clock hour: anchored RELATIVE to the sitting, 4 hours earlier.
    rice_t = h - timedelta(hours=4)
    rice_meal_type = "breakfast" if rice_t.hour < 11 else "lunch"
    return _base_profile(tz_name) + [
        {
            "data_type": "meal",
            "meal_id": "meal-rice-earlier",
            "start_time": _ms(rice_t),
            "end_time": _ms(rice_t),
            "text_repr": (
                "Meal (earlier today): rice with baingan bharta — approx 480 kcal, "
                "74g carbs, 9g protein, 5g fiber."
            ),
            "meal_type": rice_meal_type, "description": "rice with baingan bharta",
            "calories": 480, "carbs_g": 74, "protein_g": 9, "fiber_g": 5,
        },
        # The same-sitting items, logged minutes apart
        # Each item reads "light" alone; combined ≈ 1010 kcal / 107g carbs —
        # unambiguously heavy for one sitting, so a silent scan is a real
        # miss, not defensible restraint (borderline macros made the LLM
        # legitimately decline at some wall-clock hours → flaky gate).
        item(25, "meal-item-peanuts", "boiled peanuts (1 large bowl)", 280, 18, 12, 6),
        item(20, "meal-item-tindora", "tindora sabji", 130, 13, 3, 4),
        item(16, "meal-item-chapati", "2 chapatis", 120, 24, 4, 2),
        item(12, "meal-item-bhurji", "egg bhurji (2 eggs)", 230, 4, 14, 0),
        item(8, "meal-item-pav", "1 pav", 190, 36, 6, 2),
        item(2, "meal-item-salad", "cucumber, carrot and beetroot salad", 60, 12, 2, 4),
    ]


def scenario_low_intake_low_protein(tz_name: str) -> list[dict[str, Any]]:
    """Real case: whole-day intake clearly low and protein poor — the review
    said the insight should have called out calories and pushed protein up."""
    d = _today(tz_name, 6)
    return _base_profile(tz_name) + [
        {
            "data_type": "meal",
            "meal_id": "meal-small-poha",
            "start_time": _ms(_today(tz_name, 9)),
            "end_time": _ms(_today(tz_name, 9)),
            "text_repr": (
                f"Meal on {d.date().isoformat()} 9:00 AM (breakfast): small bowl "
                f"of poha — approx 180 kcal, 32g carbs, 4g protein, 2g fiber."
            ),
            "meal_type": "breakfast", "description": "small bowl of poha",
            "calories": 180, "carbs_g": 32, "protein_g": 4, "fiber_g": 2,
            "meal_time": "9:00 AM",
        },
        {
            "data_type": "meal",
            "meal_id": "meal-small-lunch",
            "start_time": _ms(_today(tz_name, 13)),
            "end_time": _ms(_today(tz_name, 13)),
            "text_repr": (
                f"Meal on {d.date().isoformat()} 1:00 PM (lunch): 1 chapati with "
                f"small bowl of dal — approx 240 kcal, 38g carbs, 9g protein, 5g fiber."
            ),
            "meal_type": "lunch", "description": "1 chapati with small bowl of dal",
            "calories": 240, "carbs_g": 38, "protein_g": 9, "fiber_g": 5,
            "meal_time": "1:00 PM",
        },
        {
            "data_type": "cgm_summary_stats",
            "start_time": _ms(d),
            "end_time": _ms(d),
            "text_repr": (
                f"CGM summary for {d.date().isoformat()} so far: average glucose "
                f"108 mg/dL, time in range 92%, no highs, no lows."
            ),
            "average_glucose": 108, "time_in_range_pct": 92,
            "hypo_events": 0, "hyper_events": 0,
        },
    ]


# -- Corner cases: the dietitian fixes tested from the OTHER direction --------
# Guard against overcorrection: numbers-first must not kill grounded praise,
# sitting-aggregation must not flag light sittings, missing macros must not
# become fabricated numbers, intake awareness must not become nagging.


def _meal_rec(tz_name: str, *, mid: str, hour: int | None = None, mins_ago_from: datetime | None = None,
              mins_ago: int = 0, desc: str, slot: str, cal: int | None, carb: int | None,
              prot: int | None, fib: int | None, time_label: str = "") -> dict[str, Any]:
    if mins_ago_from is not None:
        t = mins_ago_from - timedelta(minutes=mins_ago)
    else:
        t = _today(tz_name, hour or 12)
    macros = {}
    text_macros = []
    for key, val, unit in (("calories", cal, " kcal"), ("carbs_g", carb, "g carbs"),
                           ("protein_g", prot, "g protein"), ("fiber_g", fib, "g fiber")):
        if val is not None:
            macros[key] = val
            text_macros.append(f"{val}{unit}")
    text = f"Meal ({slot}): {desc}"
    if time_label:
        text += f" at {time_label}"
    if text_macros:
        text += " — approx " + ", ".join(text_macros) + "."
    return {
        "data_type": "meal", "meal_id": mid,
        "start_time": _ms(t), "end_time": _ms(t),
        "text_repr": text, "meal_type": slot, "description": desc,
        **macros,
    }


def scenario_genuinely_fiber_rich(tz_name: str) -> list[dict[str, Any]]:
    """Numbers SUPPORT the praise here — the agent must still celebrate."""
    return _base_profile(tz_name) + [
        _meal_rec(tz_name, mid="meal-rajma-bowl", hour=13, slot="lunch",
                  desc="rajma with brown rice and a large kachumber salad",
                  cal=520, carb=68, prot=22, fib=14),
    ]


def scenario_light_sitting(tz_name: str) -> list[dict[str, Any]]:
    """Multi-item sitting that is genuinely LIGHT — must not be flagged heavy."""
    h = _today(tz_name, 20)
    return _base_profile(tz_name) + [
        _meal_rec(tz_name, mid="meal-chilla", mins_ago_from=h, mins_ago=12, slot="dinner",
                  desc="2 moong dal chillas", cal=210, carb=22, prot=14, fib=4),
        _meal_rec(tz_name, mid="meal-chutney", mins_ago_from=h, mins_ago=8, slot="dinner",
                  desc="mint chutney", cal=25, carb=3, prot=1, fib=1),
        _meal_rec(tz_name, mid="meal-buttermilk", mins_ago_from=h, mins_ago=2, slot="dinner",
                  desc="a glass of buttermilk", cal=60, carb=5, prot=3, fib=0),
    ]


def scenario_meal_without_macros(tz_name: str) -> list[dict[str, Any]]:
    """Description-only log — no macro fields anywhere. No numbers may appear."""
    return _base_profile(tz_name) + [
        _meal_rec(tz_name, mid="meal-thali-nodata", hour=13, slot="lunch",
                  desc="home-cooked veg thali", cal=None, carb=None, prot=None, fib=None),
    ]


def scenario_snack_then_dinner(tz_name: str) -> list[dict[str, Any]]:
    """A snack 3.5h before dinner is NOT part of the dinner sitting."""
    h = _today(tz_name, 20)
    return _base_profile(tz_name) + [
        _meal_rec(tz_name, mid="meal-samosa-snack", mins_ago_from=h, mins_ago=210, slot="snack",
                  desc="one samosa with chai", cal=320, carb=35, prot=5, fib=2,
                  time_label="about 3.5 hours earlier"),
        _meal_rec(tz_name, mid="meal-palak-dinner", mins_ago_from=h, mins_ago=2, slot="dinner",
                  desc="2 phulkas with palak paneer", cal=420, carb=40, prot=18, fib=7),
    ]


def scenario_protein_rich_carb_heavy(tz_name: str) -> list[dict[str, Any]]:
    """Great protein AND heavy carbs — the headline must be the carbs."""
    return _base_profile(tz_name) + [
        _meal_rec(tz_name, mid="meal-biryani-large", hour=13, slot="lunch",
                  desc="large chicken biryani with raita", cal=780, carb=92, prot=38, fib=4),
    ]


def scenario_weight_loss_meal_event(tz_name: str) -> list[dict[str, Any]]:
    """Weight-loss patient (no CGM) logs a meal — goal framing, no glucose talk."""
    d = _today(tz_name, 6)
    now = datetime.now(ZoneInfo(tz_name))
    return [
        {
            "data_type": "profile",
            "start_time": _ms(now - timedelta(days=365)), "end_time": _ms(now),
            "text_repr": (
                "Patient profile: Rohan, 35-year-old male, no chronic "
                "conditions, goal: lose 8 kg, no medications."
            ),
            "name": "Rohan", "age": 35, "gender": "male",
            "condition": "none", "health_goal": "lose 8 kg",
        },
        _meal_rec(tz_name, mid="meal-paneer-wrap", hour=13, slot="lunch",
                  desc="grilled paneer wrap with salad", cal=420, carb=35, prot=24, fib=6),
        {
            "data_type": "vital",
            "start_time": _ms(d), "end_time": _ms(d),
            "text_repr": f"Vitals on {d.date().isoformat()}: weight 82.9 kg (down 1.3 kg over 3 weeks).",
            "weight_kg": 82.9, "weight_trend": "down 1.3 kg over 3 weeks",
        },
    ]


def scenario_adequate_day(tz_name: str) -> list[dict[str, Any]]:
    """A genuinely solid day of eating — must NOT nag about intake or protein."""
    d = _today(tz_name, 6)
    return _base_profile(tz_name) + [
        _meal_rec(tz_name, mid="meal-good-breakfast", hour=8, slot="breakfast",
                  desc="vegetable omelette with 2 rotis and curd", cal=450, carb=42, prot=26, fib=6),
        _meal_rec(tz_name, mid="meal-good-lunch", hour=13, slot="lunch",
                  desc="dal, sabji, 2 chapatis and salad", cal=560, carb=62, prot=24, fib=11),
        _meal_rec(tz_name, mid="meal-good-snack", hour=16, slot="snack",
                  desc="roasted chana and an apple", cal=220, carb=30, prot=9, fib=7),
        {
            "data_type": "cgm_summary_stats",
            "start_time": _ms(d), "end_time": _ms(d),
            "text_repr": (
                f"CGM summary for {d.date().isoformat()} so far: average glucose "
                f"114 mg/dL, time in range 91%, no highs, no lows."
            ),
            "average_glucose": 114, "time_in_range_pct": 91,
            "hypo_events": 0, "hyper_events": 0,
        },
    ]


# -- Non-meal event triggers: SMBG, symptom, missed med, CGM crossing ---------
# Each trigger gets a danger case and a false-alarm/grounding corner, matching
# production payload shapes (lib/services/vector/smbg, checkin).


def _smbg_rec(tz_name: str, *, rid: str, mgdl: float, rtype: str, notes: str = "") -> dict[str, Any]:
    t = _today(tz_name, 18)
    return {
        "data_type": "smbg", "reading_id": rid,
        "start_time": _ms(t), "end_time": _ms(t),
        "glucose_mgdl": mgdl, "reading_type": rtype, "notes": notes,
        "hour": t.hour, "source": "app",
        "text_repr": (
            f"Finger-prick glucose reading: {mgdl:.0f} mg/dL ({rtype})"
            + (f" — patient notes: {notes}" if notes else "") + "."
        ),
    }


def scenario_smbg_low_reading(tz_name: str) -> list[dict[str, Any]]:
    """Patient manually logs 58 mg/dL and feels shaky — needs first aid NOW."""
    return _base_profile(tz_name) + [
        _smbg_rec(tz_name, rid="smbg-low-58", mgdl=58, rtype="manual",
                  notes="feeling shaky and sweaty"),
    ]


def scenario_smbg_normal_reading(tz_name: str) -> list[dict[str, Any]]:
    """A perfectly normal fasting reading — calm ack, zero alarm."""
    return _base_profile(tz_name) + [
        _smbg_rec(tz_name, rid="smbg-normal-105", mgdl=105, rtype="fasting"),
    ]


def scenario_symptom_with_context(tz_name: str) -> list[dict[str, Any]]:
    """Dizziness logged right after a glucose dip — the connection is the insight."""
    d = _today(tz_name, 6)
    t = _today(tz_name, 17)
    return _base_profile(tz_name) + [
        {
            "data_type": "symptom_entry", "symptom_entry_id": "sym-dizzy-1",
            "start_time": _ms(t), "end_time": _ms(t),
            "symptom_names": ["dizziness"], "symptom_count": 1,
            "max_severity": 6, "avg_severity": 6.0, "has_notes": False,
            "text_repr": "Symptom logged: dizziness, severity 6/10.",
        },
        {
            "data_type": "cgm_summary_stats",
            "start_time": _ms(d), "end_time": _ms(d),
            "text_repr": (
                f"CGM summary for {d.date().isoformat()} so far: average glucose "
                f"117 mg/dL, one dip to 62 mg/dL about an hour ago, otherwise in range."
            ),
            "average_glucose": 117, "time_in_range_pct": 88,
            "hypo_events": 1, "lowest_glucose": 62,
        },
    ]


def scenario_symptom_no_context(tz_name: str) -> list[dict[str, Any]]:
    """A mild headache with NO related data — no cause may be invented."""
    t = _today(tz_name, 17)
    return _base_profile(tz_name) + [
        {
            "data_type": "symptom_entry", "symptom_entry_id": "sym-headache-1",
            "start_time": _ms(t), "end_time": _ms(t),
            "symptom_names": ["mild headache"], "symptom_count": 1,
            "max_severity": 3, "avg_severity": 3.0, "has_notes": False,
            "text_repr": "Symptom logged: mild headache, severity 3/10.",
        },
    ]


def scenario_med_missed_context(tz_name: str) -> list[dict[str, Any]]:
    """Missed morning metformin; day otherwise fine. Anchor carries the event."""
    d = _today(tz_name, 6)
    return _base_profile(tz_name) + [
        {
            "data_type": "cgm_summary_stats",
            "start_time": _ms(d), "end_time": _ms(d),
            "text_repr": (
                f"CGM summary for {d.date().isoformat()} so far: average glucose "
                f"131 mg/dL, time in range 79%, trending slightly higher than usual."
            ),
            "average_glucose": 131, "time_in_range_pct": 79,
        },
    ]


def scenario_cgm_severe_low(tz_name: str) -> list[dict[str, Any]]:
    """CGM crossed 54 mg/dL — the highest-stakes notification we send."""
    d = _today(tz_name, 6)
    return _base_profile(tz_name) + [
        {
            "data_type": "cgm_summary_stats",
            "start_time": _ms(d), "end_time": _ms(d),
            "text_repr": (
                f"CGM summary for {d.date().isoformat()} so far: average glucose "
                f"109 mg/dL, currently dropping, now at 54 mg/dL."
            ),
            "average_glucose": 109, "time_in_range_pct": 84, "hypo_events": 1,
        },
    ]


def scenario_cgm_high_after_meal(tz_name: str) -> list[dict[str, Any]]:
    """CGM crossed high (262) an hour after a biryani lunch — connect, don't panic."""
    d = _today(tz_name, 6)
    return _base_profile(tz_name) + [
        _meal_rec(tz_name, mid="meal-biryani-cross", hour=13, slot="lunch",
                  desc="chicken biryani", cal=680, carb=84, prot=32, fib=3),
        {
            "data_type": "cgm_summary_stats",
            "start_time": _ms(d), "end_time": _ms(d),
            "text_repr": (
                f"CGM summary for {d.date().isoformat()} so far: average glucose "
                f"138 mg/dL, rising since lunch, now at 262 mg/dL."
            ),
            "average_glucose": 138, "time_in_range_pct": 76, "hyper_events": 1,
        },
    ]


SCENARIOS = {
    "normal_day": scenario_normal_day,
    "hypo_today": scenario_hypo_today,
    "spike_after_meal": scenario_spike_after_meal,
    "weight_loss_no_cgm": scenario_weight_loss_no_cgm,
    "empty": lambda tz: [],
    "fiber_overcredit_meal": scenario_fiber_overcredit_meal,
    "carb_meal_fiber_gap": scenario_carb_meal_fiber_gap,
    "meal_items_need_aggregation": scenario_meal_items_need_aggregation,
    "low_intake_low_protein": scenario_low_intake_low_protein,
    "genuinely_fiber_rich": scenario_genuinely_fiber_rich,
    "light_sitting": scenario_light_sitting,
    "meal_without_macros": scenario_meal_without_macros,
    "snack_then_dinner": scenario_snack_then_dinner,
    "protein_rich_carb_heavy": scenario_protein_rich_carb_heavy,
    "weight_loss_meal_event": scenario_weight_loss_meal_event,
    "adequate_day": scenario_adequate_day,
    "smbg_low_reading": scenario_smbg_low_reading,
    "smbg_normal_reading": scenario_smbg_normal_reading,
    "symptom_with_context": scenario_symptom_with_context,
    "symptom_no_context": scenario_symptom_no_context,
    "med_missed_context": scenario_med_missed_context,
    "cgm_severe_low": scenario_cgm_severe_low,
    "cgm_high_after_meal": scenario_cgm_high_after_meal,
}
