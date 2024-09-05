import calendar
from typing import List, Dict
from datetime import datetime, timedelta
import pandas as pd


def split_into_days(
    start_date: datetime, end_date: datetime
) -> List[Dict[str, datetime]]:
    days = []
    current_date = start_date
    while current_date <= end_date:
        days.append(
            {
                "from_date": current_date,
                "to_date": current_date + timedelta(days=1),
            }
        )
        current_date += timedelta(days=1)
    return days


def split_into_weeks(
    start_date: datetime, end_date: datetime
) -> List[Dict[str, datetime]]:
    weeks = []
    current_date = start_date
    while current_date <= end_date:
        week_end_date = current_date + timedelta(days=6)
        if week_end_date > end_date:
            week_end_date = end_date
        weeks.append({"from_date": current_date, "to_date": week_end_date})
        current_date += timedelta(days=7)
    return weeks


def split_into_months(
    start_date: datetime, end_date: datetime
) -> List[Dict[str, datetime]]:
    months = []
    current_date = start_date.replace(
        day=1
    )  # Start from the first day of the start month
    while current_date <= end_date:
        # Calculate the last day of the current month
        last_day = calendar.monthrange(current_date.year, current_date.month)[
            1
        ]
        month_end_date = current_date.replace(day=last_day)

        # Ensure the end date does not exceed the provided end_date
        if month_end_date > end_date:
            month_end_date = end_date

        months.append({"from_date": current_date, "to_date": month_end_date})

        # Move to the first day of the next month
        next_month = current_date.month + 1 if current_date.month < 12 else 1
        next_year = (
            current_date.year
            if current_date.month < 12
            else current_date.year + 1
        )
        current_date = current_date.replace(
            year=next_year, month=next_month, day=1
        )

    return months


def get_week_start_end(date: datetime, firstweekday=calendar.MONDAY):
    # Set the first weekday (e.g., Monday)
    calendar.setfirstweekday(firstweekday)

    # Find the start of the week
    start_of_week = date - timedelta(days=date.weekday())

    # Find the end of the week
    end_of_week = start_of_week + timedelta(days=6)

    return start_of_week, end_of_week


def get_week_start_end_by_week_no(
    year: int, week_no: int, firstweekday=calendar.MONDAY
):
    # Calculate the first day of the given year
    first_day_of_year = datetime(year, 1, 1)

    # Adjust to the first weekday of the year based on the specified first weekday
    first_day_of_week = first_day_of_year - timedelta(
        days=(first_day_of_year.weekday() - firstweekday) % 7
    )

    # Calculate the start of the given week number
    week_start = first_day_of_week + timedelta(weeks=week_no - 1)

    # Calculate the end of the week
    week_end = week_start + timedelta(days=6)

    return week_start.date(), week_end.date()


def get_month_start_end(year: int, month_no: int):
    # Get the first day of the month
    start_of_month = datetime(year, month_no, 1)

    # Calculate the last day of the month
    _, last_day = calendar.monthrange(year, month_no)
    end_of_month = datetime(year, month_no, last_day)

    return start_of_month, end_of_month
