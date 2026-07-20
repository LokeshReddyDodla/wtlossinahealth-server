"""notification_budget is a deprecated shim — budgeting moved to the
Notification Broker (see tests/ai_foundation/test_notification_broker.py).

These smoke tests only pin that the shim stays permissive so any
un-migrated caller keeps working: can_send never blocks, record_sent no-ops.
"""

from lib.services.notification_budget import can_send, record_sent


def test_can_send_always_true():
    assert can_send("patient-1", "gamification") is True
    assert can_send("patient-1", "medication_reminder") is True
    assert can_send("patient-1", "anything") is True


def test_record_sent_is_noop():
    assert record_sent("patient-1") is None
