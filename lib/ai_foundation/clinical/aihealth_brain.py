"""
Importable clinical-brain entry: ``from aihealth_brain import assess``.

This is a thin land next to the June metabolic port. It does not contain
clinical coefficients. When the v2.2.0 pin-copy is dropped as
``aihealth_brain_pin.py`` beside this file (or at repo root), ``assess``
delegates to that file; otherwise it calls MetabolicEngine.assess.

Invariants applied on every return:
  - ``events`` is aliased to ``recent_cgm_events`` (and the reverse).
  - SAFETY results have lever/levers stripped (no protein_first leak).
  - A safety_floor exception fail-closes to a lever-less SAFETY contract.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Wrapper identity. The pin-copy, when present, reports its own version.
__version__ = "2.2.0-wrapper"

# Documented drop paths for the 145KB stdlib pin (v2.2.0). First match wins.
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_PIN_PATHS = (
    _HERE / "aihealth_brain_pin.py",
    _REPO_ROOT / "aihealth_brain_pin.py",
)

_pin_assess: Callable[..., Any] | None = None
_pin_resolved = False


def _is_safety_floor(exc: BaseException) -> bool:
    blob = f"{type(exc).__name__} {exc}".lower()
    return "safety_floor" in blob or "safety floor" in blob


def _fail_closed_safety() -> dict[str, Any]:
    """Minimal SAFETY contract. No predicted numbers, no levers."""
    return {
        "output_mode": "SAFETY",
        "lever": None,
        "levers": [],
        "safety_flags": ["SAFETY_FLOOR"],
        "prediction": {},
        "attribution": {},
        "fact": "",
    }


def alias_cgm_events(patient_state: dict[str, Any]) -> dict[str, Any]:
    """Copy ``events`` ↔ ``recent_cgm_events`` so either name satisfies a pin."""
    state = dict(patient_state)
    events = state.get("events")
    recent = state.get("recent_cgm_events")
    if recent is None and events is not None:
        state["recent_cgm_events"] = events
    if events is None and recent is not None:
        state["events"] = recent
    return state


def _strip_lever_fields(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if key == "lever":
                out[key] = None
            elif key == "levers":
                out[key] = []
            else:
                out[key] = _strip_lever_fields(value)
        return out
    if isinstance(obj, list):
        return [_strip_lever_fields(item) for item in obj]
    return obj


def sanitize_assess_result(result: Any) -> Any:
    """Empty every lever/levers field when output_mode is SAFETY."""
    if not isinstance(result, dict):
        return result
    mode = str(result.get("output_mode") or "").upper()
    if mode != "SAFETY":
        return result
    return _strip_lever_fields(result)


def _load_pin_assess() -> Callable[..., Any] | None:
    global _pin_assess, _pin_resolved
    if _pin_resolved:
        return _pin_assess
    for path in _PIN_PATHS:
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                "_aihealth_brain_pin", path
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            fn = getattr(module, "assess", None)
            if callable(fn):
                logger.info("aihealth_brain pin loaded from %s", path)
                _pin_assess = fn
                _pin_resolved = True
                return _pin_assess
            logger.warning("aihealth_brain pin at %s has no assess()", path)
        except Exception:
            logger.exception("aihealth_brain pin failed to load from %s", path)
    _pin_resolved = True
    _pin_assess = None
    return None


def _metabolic_assess(
    patient_state: dict[str, Any], meal: dict[str, Any]
) -> dict[str, Any]:
    from lib.ai_foundation.clinical.metabolic.engine import MetabolicEngine

    return MetabolicEngine().assess(patient_state, meal)


def backend_name() -> str:
    """Which assess implementation the next call will use."""
    return "pin" if _load_pin_assess() is not None else "metabolic_port"


def assess(
    patient_state: dict[str, Any] | None,
    meal: dict[str, Any] | None,
    **_unused: Any,
) -> dict[str, Any]:
    """Run the clinical brain. Same contract as MetabolicEngine.assess.

    Extra kwargs are ignored so a pin that grows its signature still
    imports. Patient-facing prose is not produced here.
    """
    state = alias_cgm_events(patient_state or {})
    meal_in = dict(meal or {})
    backend = _load_pin_assess() or _metabolic_assess
    try:
        raw = backend(state, meal_in)
    except Exception as exc:
        if _is_safety_floor(exc):
            logger.warning(
                "aihealth_brain safety_floor; fail-closed SAFETY, no levers"
            )
            return _fail_closed_safety()
        raise
    if not isinstance(raw, dict):
        raise TypeError("aihealth_brain assess() must return a dict")
    return sanitize_assess_result(raw)
