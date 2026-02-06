"""Helper functions for meal reminder processing."""

from datetime import date, datetime, timedelta

from sqlalchemy import exists, func
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.database import get_async_postgres_session
from lib.models.patient import Patient
from lib.models.patient_meal import PatientMeal
from lib.models.patient_permission import PatientPermission
from lib.workers.tasks.fcm.enqueue import enqueue_fcm_notification_sync

MEAL_ICONS = {
    "breakfast": "🍳",
    "lunch": "🥗",
    "dinner": "🍛",
}


def _generate_missed_meal_message(days_missed: list[date], first_name: str) -> str:
    """Generate personalized message for missed meals."""
    missed_count = len(days_missed)

    if len(days_missed) == 1:
        return (
            f"Looks like you missed logging your meal yesterday, {first_name}. "
            "Let's fix that today!"
        )
    elif len(days_missed) < 4:
        return (
            f"You've missed {missed_count} days of meal logs recently, {first_name}. "
            "Logging helps us personalize your care – let's catch up!"
        )
    else:
        return (
            f"{first_name}, you haven't logged meals for several days. "
            "Consistency is key for great health – we believe in you! 💪"
        )


def _send_reminder_notification(
    patient_id: str, first_name: str, title: str, body: str
) -> None:
    """Send FCM notification to a patient."""
    enqueue_fcm_notification_sync(
        participants=[{"id": patient_id}],
        notification_info={
            "title": title,
            "body": body,
            "channel_key": "reminders",
            "group_key": "reminder_group",
            "data": {"type": "reminder", "screen": "meal_log"},
        },
    )


async def process_meal_reminder_for_type(meal_type: str) -> None:
    """Send reminders to patients who haven't uploaded a specific meal today."""
    async with get_async_postgres_session() as session:
        today = datetime.now().date()
        meal_type_lower = meal_type.lower()

        # Filter patients with notification permissions and no meal today
        stmt = (
            select(Patient)
            .join(PatientPermission)
            .where(PatientPermission.notification_permission.is_(True))
            .where(
                ~exists(
                    select(PatientMeal.meal_id).where(
                        PatientMeal.patient_id == Patient.patient_id,
                        PatientMeal.date == today,
                        func.lower(PatientMeal.type) == meal_type_lower,
                    )
                )
            )
            .options(selectinload(Patient.permissions))
        )

        result = await session.execute(stmt)
        patients = result.scalars().all()

        for patient in patients:
            first_name = patient.first_name or "there"
            meal_label = meal_type.capitalize()
            meal_icon = MEAL_ICONS.get(meal_type_lower, "🍽️")

            title = f"{meal_icon} {first_name}, log your {meal_label}"
            body = (
                f"Logging your {meal_label.lower()} helps keep your nutrition on track. "
                "Tap to upload it now! 🙌"
            )

            _send_reminder_notification(
                str(patient.patient_id), first_name, title, body
            )


async def process_missed_meals_check() -> None:
    """Send reminders to users who haven't uploaded meals in the last few days."""
    async with get_async_postgres_session() as session:
        today = datetime.now().date()
        past_7_days = [today - timedelta(days=i) for i in range(1, 8)]
        start_date = past_7_days[-1]

        # Get patients with notification permissions
        stmt = (
            select(Patient)
            .join(PatientPermission)
            .where(PatientPermission.notification_permission.is_(True))
            .options(
                selectinload(Patient.permissions),
                selectinload(Patient.meals).where(
                    PatientMeal.date >= start_date, PatientMeal.date < today
                ),
            )
        )

        result = await session.execute(stmt)
        patients = result.scalars().all()

        for patient in patients:
            meal_dates = {m.date for m in patient.meals}
            days_missed = [d for d in past_7_days if d not in meal_dates]

            if not days_missed:
                continue

            first_name = str(patient.first_name) or "there"
            title = f"🍽️ {first_name}, missed some meals?"
            body = _generate_missed_meal_message(days_missed, first_name)

            _send_reminder_notification(
                str(patient.patient_id), first_name, title, body
            )
