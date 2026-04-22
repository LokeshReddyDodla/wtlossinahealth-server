"""Config-driven value coercion for profile-agent draft changes.

The LLM emits string values; before applying we coerce to typed Python
values and reject out-of-range / non-enum input. All rules come from
the field's config entry — there is no per-field branch here.
"""

from __future__ import annotations

import re
from datetime import date as _date
from datetime import time as _time
from typing import Any, Dict, List, Tuple

from lib.services.profile_agent.config import FIELD_TO_CONFIG, FieldConfig

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
_BOOL_TRUE = {"yes", "true", "1", "y"}
_BOOL_FALSE = {"no", "false", "0", "n"}


def coerce_value(field_key: str, raw: Any) -> Any:
    """Coerce a raw (usually string) value to its typed Python form.

    Raises ValueError with a user-facing message when invalid.
    """
    cfg = FIELD_TO_CONFIG.get(field_key)
    if cfg is None:
        raise ValueError(f"unknown field: {field_key}")

    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        raise ValueError(f"{cfg['label']} cannot be empty.")

    t = cfg["type"]

    if t == "string":
        if field_key == "email" and not _EMAIL_RE.match(str(raw).strip().lower()):
            raise ValueError("That doesn't look like a valid email address.")
        return str(raw).strip() if field_key != "email" else str(raw).strip().lower()

    if t == "int":
        try:
            v = int(str(raw).strip())
        except (ValueError, TypeError):
            raise ValueError(f"{cfg['label']} must be a whole number.")
        return _check_range(cfg, v)

    if t == "float":
        try:
            v = float(str(raw).strip())
        except (ValueError, TypeError):
            raise ValueError(f"{cfg['label']} must be a number.")
        return _check_range(cfg, v)

    if t == "bool":
        s = str(raw).strip().lower()
        if s in _BOOL_TRUE:
            return True
        if s in _BOOL_FALSE:
            return False
        raise ValueError(f"{cfg['label']}: please answer yes or no.")

    if t == "date":
        try:
            return _date.fromisoformat(str(raw).strip())
        except (ValueError, TypeError):
            raise ValueError(f"{cfg['label']} must be in YYYY-MM-DD format.")

    if t == "time":
        try:
            return _time.fromisoformat(str(raw).strip())
        except (ValueError, TypeError):
            raise ValueError(f"{cfg['label']} must be in HH:MM format.")

    if t == "enum":
        values: List[Any] = cfg.get("values", [])
        s = str(raw).strip()
        for v in values:
            if isinstance(v, str) and s.lower() == v.lower():
                return v
            if s == str(v):
                return v
        raise ValueError(f"{cfg['label']} must be one of: {', '.join(str(v) for v in values)}.")

    if t == "list_of_string":
        if isinstance(raw, list):
            items = [str(x).strip() for x in raw if str(x).strip()]
        else:
            items = [x.strip() for x in str(raw).split(",") if x.strip()]
        return items

    raise ValueError(f"unsupported type for {field_key}: {t}")


def _check_range(cfg: FieldConfig, value: float | int) -> float | int:
    r = cfg.get("range")
    if r and not (r[0] <= value <= r[1]):
        raise ValueError(f"{cfg['label']} should be between {r[0]} and {r[1]}.")
    return value


def validate_draft(
    draft_changes: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """Validate every field in the draft. Returns (coerced, errors)."""
    coerced: Dict[str, Any] = {}
    errors: List[str] = []
    for field_key, raw in draft_changes.items():
        if field_key not in FIELD_TO_CONFIG:
            errors.append(f"unknown field: {field_key}")
            continue
        try:
            coerced[field_key] = coerce_value(field_key, raw)
        except ValueError as exc:
            errors.append(str(exc))
    return coerced, errors
