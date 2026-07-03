"""
Shared numeric/time helpers for the metabolic module.

Single source of truth for meal-slot boundaries — these match the GBM spike
model's feature encoding (engine.slot), so all slot bucketing across the
module must agree with them.
"""

from __future__ import annotations

import math

SLOT_NAMES = ("breakfast", "lunch", "dinner", "snack")


def num(x) -> float | None:
    """Coerce to a finite float, else None."""
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def slot_index(h) -> int:
    """Hour → slot index (0=breakfast, 1=lunch, 2=dinner, 3=snack)."""
    return 0 if 5 <= h < 11 else 1 if 11 <= h < 16 else 2 if 16 <= h < 22 else 3


def meal_slot(hour: float | None) -> str:
    """Hour → slot name. None defaults to lunch (midday assumption)."""
    if hour is None:
        return "lunch"
    return SLOT_NAMES[slot_index(int(hour))]
