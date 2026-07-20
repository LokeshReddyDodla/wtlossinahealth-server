"""DEPRECATED — budgeting now lives in the Notification Broker.

The old single blind 8/day counter was category-blind (critical meds starved
insights) and server-tz. The broker (lib/services/notifications/broker.py +
policy.py + budget.py) replaced it with per-category, patient-local caps at
the single delivery choke point.

These shims stay only so any un-migrated caller keeps working: ``can_send``
never blocks (the broker decides), ``record_sent`` is a no-op (the broker
counts). Remove once no imports remain.
"""

from __future__ import annotations


def can_send(patient_id: str, notification_type: str) -> bool:
    return True


def record_sent(patient_id: str) -> None:
    return None
