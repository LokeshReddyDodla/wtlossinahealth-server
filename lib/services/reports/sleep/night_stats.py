from typing import Optional

from .queries import generate_fragmentation_query, generate_night_stats_query

RECOMMENDED_MIN_MINUTES = 420.0  # AASM: adults need >= 7h
MIN_NIGHTS_FOR_VARIABILITY = 3  # variability is meaningless from one or two nights
_SCORE_ZERO_SD = 120.0  # timing SD (min) at which the consistency score hits 0


def _round(value: Optional[float], ndigits: int = 1) -> Optional[float]:
    return None if value is None else round(value, ndigits)


def derive(
    nights: int,
    total_asleep: Optional[float],
    avg_asleep: Optional[float],
    longest: Optional[float],
    shortest: Optional[float],
    bedtime_sd: Optional[float],
    wake_sd: Optional[float],
    days_covered: int,
    total_awakenings: Optional[float] = 0,
    total_waso: Optional[float] = 0,
) -> dict:
    """Turn the raw per-night aggregates into duration + consistency dicts.

    Kept pure (no ClickHouse) so the math is unit-testable. Duration is built
    from asleep time only, so it never carries the double-counted in-bed
    envelope the old segment-sum query did.
    """
    nights = int(nights or 0)
    total_asleep = total_asleep or 0

    if nights >= MIN_NIGHTS_FOR_VARIABILITY and bedtime_sd is not None and wake_sd is not None:
        avg_sd = (bedtime_sd + wake_sd) / 2
        # 0 min SD -> 100; _SCORE_ZERO_SD -> 0. A product score, not a validated
        # instrument — the raw SD minutes are the clinical figure.
        consistency_score = round(max(0.0, 100.0 - avg_sd * (100.0 / _SCORE_ZERO_SD)), 1)
        bedtime_var = round(bedtime_sd, 1)
        wake_var = round(wake_sd, 1)
    else:
        consistency_score = bedtime_var = wake_var = None

    if avg_asleep and avg_asleep > 0:
        avg_sleep = round(avg_asleep, 1)
        debt = round(max(0.0, RECOMMENDED_MIN_MINUTES - avg_asleep), 1)
    else:
        avg_sleep = debt = None

    per_day_avg = (total_asleep / days_covered) if days_covered > 0 else 0

    # Fragmentation is averaged over tracked nights, so a flawless night
    # contributes a 0 rather than being dropped.
    if nights > 0:
        avg_awakenings = round((total_awakenings or 0) / nights, 1)
        avg_waso = round((total_waso or 0) / nights, 1)
    else:
        avg_awakenings = avg_waso = None

    return {
        "duration": {
            "total_duration": round(total_asleep, 1) if total_asleep else 0,
            "average_duration": avg_sleep,
            "per_day_average_duration": round(per_day_avg, 1),
            "longest_sleep": _round(longest),
            "shortest_sleep": _round(shortest),
        },
        "consistency": {
            "nights_tracked": nights,
            "bedtime_variability_minutes": bedtime_var,
            "wake_variability_minutes": wake_var,
            "consistency_score": consistency_score,
            "average_nightly_sleep_minutes": avg_sleep,
            "recommended_min_minutes": RECOMMENDED_MIN_MINUTES,
            "sleep_debt_minutes": debt,
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
    ) -> dict:
        query = generate_night_stats_query(patient_id, start_datetime, end_datetime)
        result = clickhouse_store.client.execute(query)
        row = result[0] if result else (0, 0, None, None, None, None, None)

        frag = clickhouse_store.client.execute(
            generate_fragmentation_query(patient_id, start_datetime, end_datetime)
        )
        frag_row = frag[0] if frag else (0, 0)

        return derive(
            nights=row[0],
            total_asleep=row[1],
            avg_asleep=row[2],
            longest=row[3],
            shortest=row[4],
            bedtime_sd=row[5],
            wake_sd=row[6],
            days_covered=days_covered,
            total_awakenings=frag_row[0],
            total_waso=frag_row[1],
        )
