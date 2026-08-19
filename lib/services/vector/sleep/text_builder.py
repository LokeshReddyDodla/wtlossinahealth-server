"""Text representation for a daily sleep report."""

from typing import Any


def _hm(minutes: Any) -> str:
    if minutes is None:
        return "n/a"
    m = int(round(float(minutes)))
    return f"{m // 60}h{m % 60:02d}m"


def build_sleep_text(start_str: str, end_str: str, report: dict[str, Any]) -> str:
    duration = report.get("duration") or {}
    quality = report.get("quality") or {}
    timing = report.get("timing") or {}
    consistency = report.get("consistency") or {}
    trend = report.get("trend") or {}
    dist = (report.get("type_distribution") or {}).get("distribution") or {}

    def stage_min(stage: str) -> Any:
        return (dist.get(stage) or {}).get("total_duration")

    parts = [
        f"Sleep summary from {start_str} to {end_str}:",
        f"total asleep {_hm(duration.get('total_duration'))},",
        f"deep {_hm(stage_min('sleep_deep'))}, rem {_hm(stage_min('sleep_rem'))}, "
        f"light {_hm(stage_min('sleep_light'))}, awake {_hm(stage_min('sleep_awake'))}.",
        f"efficiency {quality.get('sleep_efficiency')}%, restorative {quality.get('restorative_sleep')}%, "
        f"quality {quality.get('sleep_quality')}.",
    ]

    if quality.get("average_awakenings") is not None:
        parts.append(
            f"awakenings/night {quality.get('average_awakenings')}, "
            f"WASO {_hm(quality.get('average_waso_minutes'))}."
        )

    if timing.get("average_start_time"):
        parts.append(
            f"bedtime {timing.get('average_start_time')}, wake {timing.get('average_end_time')}."
        )

    if consistency.get("consistency_score") is not None:
        parts.append(f"consistency score {consistency.get('consistency_score')}/100.")
    if consistency.get("sleep_debt_minutes"):
        parts.append(f"sleep debt {_hm(consistency.get('sleep_debt_minutes'))}/night.")
    if consistency.get("subjective_quality") is not None:
        parts.append(f"self-rated quality {consistency.get('subjective_quality')}/5.")

    if trend.get("delta_average_sleep_minutes") is not None:
        parts.append(
            f"trend vs previous period: {trend.get('delta_average_sleep_minutes'):+.0f} min sleep, "
            f"{trend.get('delta_efficiency', 0) or 0:+.0f}% efficiency."
        )

    return " ".join(parts)
