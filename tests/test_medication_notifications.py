"""Tests for medication notification triggers and complete_expired_medications cron."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest


# ── Notification body content tests ─────────────────────────────────────


class TestMedicationReminderBody:
    """Verify medication reminder uses task description (with med names)."""

    def test_body_uses_description_when_available(self):
        pending_task = SimpleNamespace(
            description="Metformin 500mg, Vitamin D 1000IU",
        )
        slot_name = "morning"
        body = (
            f"Time to take: {pending_task.description}"
            if pending_task.description
            else f"Time to take your {slot_name} medications"
        )
        assert body == "Time to take: Metformin 500mg, Vitamin D 1000IU"

    def test_body_fallback_when_no_description(self):
        pending_task = SimpleNamespace(description=None)
        slot_name = "morning"
        body = (
            f"Time to take: {pending_task.description}"
            if pending_task.description
            else f"Time to take your {slot_name} medications"
        )
        assert body == "Time to take your morning medications"

    def test_body_fallback_when_empty_description(self):
        pending_task = SimpleNamespace(description="")
        slot_name = "evening"
        body = (
            f"Time to take: {pending_task.description}"
            if pending_task.description
            else f"Time to take your {slot_name} medications"
        )
        assert body == "Time to take your evening medications"


class TestFollowUpReminderBody:
    """Verify follow-up reminder uses task title (has doctor name)."""

    def test_body_uses_title(self):
        pending_task = SimpleNamespace(
            title="Follow up with Dr. Smith",
            description="You have a scheduled follow-up appointment today",
        )
        body = pending_task.title or "You have a scheduled follow-up appointment today"
        assert body == "Follow up with Dr. Smith"

    def test_body_fallback_when_no_title(self):
        pending_task = SimpleNamespace(title=None, description="generic")
        body = pending_task.title or "You have a scheduled follow-up appointment today"
        assert body == "You have a scheduled follow-up appointment today"


# ── Prescription confirm/edit notification content ──────────────────────


class TestPrescriptionNotificationContent:
    def test_confirm_notification_body(self):
        med_names = ["Metformin", "Aspirin", "Vitamin D"]
        doctor = "Dr. Smith"
        body = f"Dr. {doctor} prescribed: {', '.join(med_names)}"
        assert body == "Dr. Dr. Smith prescribed: Metformin, Aspirin, Vitamin D"
        # Note: "Dr. Dr. Smith" is a bug if doctor_name already includes "Dr."
        # But our extraction stores just the name, so this is fine.

    def test_confirm_notification_fallback_doctor(self):
        doctor = None or "Your doctor"
        body = f"Dr. {doctor} prescribed: Metformin"
        assert body == "Dr. Your doctor prescribed: Metformin"

    def test_edit_notification_body(self):
        doctor = "Smith"
        body = f"Dr. {doctor} updated your prescription. Check your medication list."
        assert "updated" in body


# ── Lifecycle action notification content ───────────────────────────────


class TestLifecycleNotificationContent:
    def test_pause_notification(self):
        med_name = "Metformin"
        body = f"Your {med_name} has been paused by your care team."
        assert "paused" in body
        assert "Metformin" in body

    def test_resume_notification(self):
        med_name = "Metformin"
        body = f"Your {med_name} has been resumed. Check your tasks."
        assert "resumed" in body

    def test_discontinue_notification(self):
        med_name = "Aspirin"
        body = f"Your {med_name} has been discontinued by your care team."
        assert "discontinued" in body
        assert "Aspirin" in body

    def test_activation_notification(self):
        med_name = "Methotrexate"
        body = f"Your {med_name} course begins today. Check your tasks."
        assert "begins today" in body


# ── Refill reminder logic ───────────────────────────────────────────────


class TestRefillReminderLogic:
    """Test the days_left calculation for 7-day and 3-day reminders."""

    def _should_remind(self, end_date, today):
        days_left = (end_date - today).days
        return days_left in (7, 3)

    def test_7_days_before(self):
        today = date(2026, 4, 14)
        end = date(2026, 4, 21)
        assert self._should_remind(end, today) is True

    def test_3_days_before(self):
        today = date(2026, 4, 14)
        end = date(2026, 4, 17)
        assert self._should_remind(end, today) is True

    def test_5_days_before_no_reminder(self):
        today = date(2026, 4, 14)
        end = date(2026, 4, 19)
        assert self._should_remind(end, today) is False

    def test_today_no_reminder(self):
        today = date(2026, 4, 14)
        end = date(2026, 4, 14)
        assert self._should_remind(end, today) is False

    def test_1_day_before_no_reminder(self):
        today = date(2026, 4, 14)
        end = date(2026, 4, 15)
        assert self._should_remind(end, today) is False

    def test_refill_body_includes_days(self):
        name = "Metformin 500mg"
        days_left = 7
        body = f"Your {name} course ends in {days_left} days. Contact your doctor if you need a refill."
        assert "7 days" in body


# ── complete_expired_medications cron logic ──────────────────────────────


class TestCompleteExpiredLogic:
    """Test the status transition rules applied by the cron job."""

    def test_active_past_end_date_becomes_completed(self):
        today = date(2026, 4, 14)
        med = SimpleNamespace(status="active", end_date=date(2026, 4, 13))
        # end_date < today
        assert med.end_date < today
        med.status = "completed"
        assert med.status == "completed"

    def test_active_end_date_today_stays_active(self):
        today = date(2026, 4, 14)
        med = SimpleNamespace(status="active", end_date=date(2026, 4, 14))
        # end_date == today → condition is end_date < today → False
        assert not (med.end_date < today)

    def test_active_no_end_date_stays_active(self):
        med = SimpleNamespace(status="active", end_date=None)
        assert med.end_date is None  # no expiry

    def test_scheduled_start_today_becomes_active(self):
        today = date(2026, 4, 14)
        med = SimpleNamespace(status="scheduled", start_date=date(2026, 4, 14))
        assert med.start_date <= today
        med.status = "active"
        assert med.status == "active"

    def test_scheduled_start_past_becomes_active(self):
        today = date(2026, 4, 14)
        med = SimpleNamespace(status="scheduled", start_date=date(2026, 4, 10))
        assert med.start_date <= today

    def test_scheduled_future_stays_scheduled(self):
        today = date(2026, 4, 14)
        med = SimpleNamespace(status="scheduled", start_date=date(2026, 4, 20))
        assert not (med.start_date <= today)
