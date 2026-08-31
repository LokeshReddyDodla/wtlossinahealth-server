"""Preview stashes each item's box_2d by trace_id; save restores it by name for
clients that don't echo box_2d back. Only box_2d is cached."""

import json
import logging

logger = logging.getLogger(__name__)

_NAMESPACE = "meal_box2d"
_TTL_SECONDS = 24 * 60 * 60


def _store():
    # Lazy import: container.py imports MealService during init, so a top-level
    # container import here would be circular.
    from lib.core.container import container

    return container.resolve(_NAMESPACE)


async def cache_extraction_boxes(trace_id: str | None, items) -> None:
    if not trace_id:
        return
    boxes = [
        {"name": it.name, "box_2d": it.box_2d}
        for it in items
        if getattr(it, "box_2d", None)
    ]
    if not boxes:
        return
    try:
        await _store().aset_key(trace_id, json.dumps(boxes), expire=_TTL_SECONDS)
    except Exception:
        logger.warning("meal box2d cache write failed (trace=%s)", trace_id, exc_info=True)


async def restore_extraction_boxes(trace_id: str | None, items) -> None:
    if not trace_id or not items or all(getattr(it, "box_2d", None) for it in items):
        return
    try:
        raw = await _store().aget_key(trace_id)
    except Exception:
        logger.warning("meal box2d cache read failed (trace=%s)", trace_id, exc_info=True)
        return
    if not raw:
        return
    try:
        cached = json.loads(raw)
    except (ValueError, TypeError):
        return

    by_name: dict[str, list] = {}
    for entry in cached:
        name = (entry.get("name") or "").strip().lower()
        box = entry.get("box_2d")
        if name and box:
            by_name.setdefault(name, box)

    for it in items:
        if getattr(it, "box_2d", None):
            continue
        box = by_name.get((it.name or "").strip().lower())
        if box:
            it.box_2d = box
