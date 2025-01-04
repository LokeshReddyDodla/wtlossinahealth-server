import math


def validate_float(value: float) -> float:
    if value is None or math.isnan(value) or not math.isfinite(value):
        return 0.0
    return value
