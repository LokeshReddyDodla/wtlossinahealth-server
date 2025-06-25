from datetime import datetime, timedelta, date
from sqlalchemy.future import select

from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.tasks.fcm_tasks import send_fcm_notification_task
from sqlalchemy.orm import selectinload

# Define default meal time windows (used for fallback logic if needed)
DEFAULT_MEAL_WINDOWS = {
    "breakfast": {"start": 6, "end": 10},
    "lunch": {"start": 11, "end": 14},
    "dinner": {"start": 19, "end": 22},
}


async def process_meal_reminder_for_type(meal_type: str):
    """
    Send reminders to patients who haven't uploaded a specific meal today.
    E.g., breakfast by 10:30 AM, lunch by 2:30 PM, dinner by 10:30 PM
    """
    async with get_postgres_session() as session:
        today = datetime.now().date()

        result = await session.execute(
            select(Patient).options(
                selectinload(Patient.permissions), selectinload(Patient.meals)
            )
        )
        patients = result.scalars().all()

        for patient in patients:
            if not _can_notify(patient):
                continue

            meals_today = [
                m
                for m in patient.meals
                if m.date == today and m.type.lower() == meal_type
            ]

            if meals_today:
                continue

            first_name = patient.first_name or "there"
            meal_label = meal_type.capitalize()

            title = (
                f"[BETA] Hey {first_name}, don't forget your {meal_label} 🍽️"
            )
            # body = f"Logging your {meal_label.lower()} helps keep your nutrition on track. Tap to upload it now!"
            body = (
                f"Logging your {meal_label.lower()} helps keep your nutrition on track. "
                "Tap to upload it now!\n\n(This feature is in testing – feedback welcome 🙌)"
            )

            participants = [{"id": str(patient.patient_id), "is_muted": False}]

            send_fcm_notification_task.delay(
                participants=participants,
                notification_info={
                    "title": title,
                    "body": body,
                    "channel_key": "reminders",
                    "group_key": "reminder_group",
                    "data": {"type": "reminder", "screen": "meal_log"},
                },
            )


async def process_missed_meals_check():
    """
    General reminder: Send to users who haven’t uploaded meals in the last few days.
    """
    async with get_postgres_session() as session:
        today = datetime.now().date()
        past_7_days = [today - timedelta(days=i) for i in range(1, 8)]

        result = await session.execute(
            select(Patient).options(
                selectinload(Patient.permissions), selectinload(Patient.meals)
            )
        )
        patients = result.scalars().all()

        for patient in patients:
            if not _can_notify(patient):
                continue

            meal_dates = {
                m.date for m in patient.meals if m.date in past_7_days
            }

            days_missed = [d for d in past_7_days if d not in meal_dates]

            if not days_missed:
                continue

            first_name = str(patient.first_name) or "there"
            title = f"[BETA] Hey {first_name}, let's get back on track! 🍱"
            body = f"{_generate_missed_meal_message(days_missed, first_name)}\n\n(This feature is in testing – feedback welcome 🙌)"

            send_fcm_notification_task.delay(
                participants=[
                    {"id": str(patient.patient_id), "is_muted": False}
                ],
                notification_info={
                    "title": title,
                    "body": body,
                    "channel_key": "reminders",
                    "group_key": "reminder_group",
                    "data": {"type": "reminder", "screen": "meal_log"},
                },
            )


def _generate_missed_meal_message(
    days_missed: list[date], first_name: str
) -> str:
    missed_count = len(days_missed)

    if len(days_missed) == 1:
        return f"Looks like you missed logging your meal yesterday, {first_name}. Let’s fix that today!"
    elif len(days_missed) < 4:
        return (
            f"You’ve missed {missed_count} days of meal logs recently, {first_name}. "
            "Logging helps us personalize your care – let’s catch up!"
        )
    else:
        return (
            f"{first_name}, you haven’t logged meals for several days. "
            "Consistency is key for great health – we believe in you! 💪"
        )


def _can_notify(patient: Patient) -> bool:
    return (
        patient.permissions is not None
        and patient.permissions.notification_permission
    )
