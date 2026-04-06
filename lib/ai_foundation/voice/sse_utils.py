"""SSE parsing utility for voice module."""

from __future__ import annotations

import json


def parse_sse_event(raw: str) -> tuple[str | None, dict]:
    """Extract event name and parsed data from a raw SSE string.

    Returns (event_name, event_data) where event_data defaults to {}
    if missing or unparseable.
    """
    event_name = None
    data_str = None

    for line in raw.strip().split("\n"):
        if line.startswith("event: "):
            event_name = line[7:].strip()
        elif line.startswith("data: "):
            data_str = line[6:].strip()

    if event_name is None:
        return None, {}

    event_data: dict = {}
    if data_str:
        try:
            event_data = json.loads(data_str)
        except (json.JSONDecodeError, TypeError):
            pass

    return event_name, event_data
