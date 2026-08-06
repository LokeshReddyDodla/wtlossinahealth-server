from datetime import timedelta
from statistics import mean, pstdev
from typing import List, Optional

from .queries import generate_fragmentation_query, generate_night_stats_query

RECOMMENDED_MIN_MINUTES = 420.0  # AASM adult floor (>= 7h); overridden by age
MIN_NIGHTS_FOR_VARIABILITY = 3  # variability is meaningless from one or two nights
_SCORE_ZERO_SD = 120.0  # timing SD (min) at which the consistency score hits 0


def recommended_minimum_for_age(age) -> float:
    """AASM/NSF age-banded nightly minimum. Teens need more than adults; the
    adult floor holds for everyone 18+."""
    if age is not None and age < 18:
        return 480.0  # 13-17: >= 8h
    return RECOMMENDED_MIN_MINUTES  # 18+: >= 7h


def _clock_to_min_since_noon(hhmm: Optional[str]) -> Optional[float]:
    """"HH:MM" -> minutes from that night's noon anchor, matching the wearable
    frame (evening = small positive, after-midnight = larger). So bedtimes on
    either side of midnight sit on one monotonic axis."""
    if not hhmm or ":" not in hhmm:
        return None
    try:
        h, m = hhmm.split(":")[:2]
        return ((int(h) - 12) % 24) * 60 + int(m)
    except (ValueError, TypeError):
        return None


def _empty(recommended_min: float = RECOMMENDED_MIN_MINUTES) -> dict:
    return {
        "duration": {
            "total_duration": 0,
            "average_duration": None,
            "per_day_average_duration": 0,
            "longest_sleep": None,
            "shortest_sleep": None,
        },
        "consistency": {
            "nights_tracked": 0,
            "bedtime_variability_minutes": None,
            "wake_variability_minutes": None,
            "consistency_score": None,
            "average_nightly_sleep_minutes": None,
            "recommended_min_minutes": recommended_min,
            "sleep_debt_minutes": None,
            "wearable_nights": 0,
            "manual_nights": 0,
            "subjective_quality": None,
        },
        "fragmentation": {"average_awakenings": None, "average_waso_minutes": None},
    }


def derive_nights(
    nights: List[dict],
    total_awakenings: Optional[float],
    total_waso: Optional[float],
    days_covered: int,
    recommended_min: float = RECOMMENDED_MIN_MINUTES,
) -> dict:
    """Aggregate reconciled per-night rows into the report blocks. Each night is
    {asleep, bed_min, wake_min, source, quality?}. Duration/consistency/debt span
    every night; fragmentation is wearable-only (a person can't report awakenings).
    """
    nights = [x for x in nights if (x.get("asleep") or 0) > 0]
    n = len(nights)
    if n == 0:
        return _empty(recommended_min)

    wearable_nights = sum(1 for x in nights if x["source"] == "wearable")
    manual_nights = n - wearable_nights

    asleeps = [x["asleep"] for x in nights]
    total_asleep = sum(asleeps)
    avg_asleep = mean(asleeps)

    beds = [x["bed_min"] for x in nights if x.get("bed_min") is not None]
    wakes = [x["wake_min"] for x in nights if x.get("wake_min") is not None]
    if (
        len(beds) >= MIN_NIGHTS_FOR_VARIABILITY
        and len(wakes) >= MIN_NIGHTS_FOR_VARIABILITY
    ):
        bed_sd, wake_sd = pstdev(beds), pstdev(wakes)
        avg_sd = (bed_sd + wake_sd) / 2
        # A product score, not a validated instrument — the raw SD is the figure.
        consistency_score = round(max(0.0, 100.0 - avg_sd * (100.0 / _SCORE_ZERO_SD)), 1)
        bed_var, wake_var = round(bed_sd, 1), round(wake_sd, 1)
    else:
        consistency_score = bed_var = wake_var = None

    qualities = [x["quality"] for x in nights if x.get("quality") is not None]
    subjective_quality = round(mean(qualities), 1) if qualities else None

    if wearable_nights > 0:
        avg_awakenings = round((total_awakenings or 0) / wearable_nights, 1)
        avg_waso = round((total_waso or 0) / wearable_nights, 1)
    else:
        avg_awakenings = avg_waso = None

    per_day_avg = (total_asleep / days_covered) if days_covered > 0 else 0

    return {
        "duration": {
            "total_duration": round(total_asleep, 1),
            "average_duration": round(avg_asleep, 1),
            "per_day_average_duration": round(per_day_avg, 1),
            "longest_sleep": round(max(asleeps), 1),
            "shortest_sleep": round(min(asleeps), 1),
        },
        "consistency": {
            "nights_tracked": n,
            "bedtime_variability_minutes": bed_var,
            "wake_variability_minutes": wake_var,
            "consistency_score": consistency_score,
            "average_nightly_sleep_minutes": round(avg_asleep, 1),
            "recommended_min_minutes": recommended_min,
            "sleep_debt_minutes": round(max(0.0, recommended_min - avg_asleep), 1),
            "wearable_nights": wearable_nights,
            "manual_nights": manual_nights,
            "subjective_quality": subjective_quality,
        },
        "fragmentation": {
            "average_awakenings": avg_awakenings,
            "average_waso_minutes": avg_waso,
        },
    }


class SleepNightStatistics:
    @staticmethod
    def fetch(
        clickhouse_store,
        patient_id: str,
        start_datetime: str,
        end_datetime: str,
        days_covered: int,
        sleep_checkins: Optional[List[dict]] = None,
        recommended_min: float = RECOMMENDED_MIN_MINUTES,
    ) -> dict:
        rows = clickhouse_store.client.execute(
            generate_night_stats_query(patient_id, start_datetime, end_datetime)
        )
        nights: List[dict] = []
        wearable_dates = set()
        for r in rows:
            wearable_dates.add(r[0])
            nights.append(
                {
                    "date": r[0],
                    "bed_min": r[1],
                    "wake_min": r[2],
                    "asleep": r[3],
                    "source": "wearable",
                }
            )

        frag = clickhouse_store.client.execute(
            generate_fragmentation_query(patient_id, start_datetime, end_datetime)
        )
        frag_row = frag[0] if frag else (0, 0)

        # Fold in manual check-ins only for nights the device didn't cover. The
        # ±1-day window absorbs the evening-vs-wake-date convention gap, so one
        # night is never counted from both sources (wearable always wins).
        for c in sleep_checkins or []:
            cd = c.get("checkin_date")
            if cd is None:
                continue
            if cd in wearable_dates or (cd - timedelta(days=1)) in wearable_dates:
                continue
            hours = c.get("hours_slept") or 0
            nights.append(
                {
                    "date": cd,
                    "bed_min": _clock_to_min_since_noon(c.get("bed_time")),
                    "wake_min": _clock_to_min_since_noon(c.get("wake_time")),
                    "asleep": hours * 60.0,
                    "quality": c.get("quality"),
                    "source": "manual",
                }
            )

        return derive_nights(
            nights, frag_row[0], frag_row[1], days_covered, recommended_min
        )
