import calendar
from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd


def split_into_days(
    start_date: datetime, end_date: datetime
) -> List[Dict[str, datetime]]:
    days = []
    current_date = start_date
    while current_date <= end_date:
        days.append(
            {
                "start_date": current_date,
                "end_date": current_date + timedelta(days=1),
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
        weeks.append({"start_date": current_date, "end_date": week_end_date})
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

        months.append({"start_date": current_date, "end_date": month_end_date})

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


def get_week_start_and_end_from_week_no(
    year: int, week_no: int, firstweekday=calendar.MONDAY
):
    # Get the first day of the year
    first_day_of_year = datetime(year, 1, 1)

    # Calculate the start of the week (Monday)
    start_of_week = first_day_of_year + timedelta(weeks=week_no - 1)

    # Align to the first Monday of the week (ISO standard)
    start_of_week = start_of_week - timedelta(days=start_of_week.weekday())
    start_of_week = start_of_week.replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # Calculate the end of the week (Sunday)
    end_of_week = start_of_week + timedelta(days=6)
    end_of_week = end_of_week.replace(
        hour=23, minute=59, second=59, microsecond=0
    )

    return start_of_week, end_of_week


def get_month_start_end(year: int, month_no: int):
    start_of_month = datetime(year, month_no, 1)
    _, last_day = calendar.monthrange(year, month_no)
    end_of_month = datetime(year, month_no, last_day, 23, 59, 59)

    return start_of_month, end_of_month


def get_months_between_dates(
    start_date: datetime, end_date: datetime
) -> List[tuple]:
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    # Start from the month and year of start_date
    start_year, start_month = start_date.year, start_date.month
    end_year, end_month = end_date.year, end_date.month

    months = []
    for year in range(start_year, end_year + 1):
        # Determine the start and end months for the current year
        month_start = start_month if year == start_year else 1
        month_end = end_month if year == end_year else 12

        # Add all (year, month) tuples for the current year
        for month in range(month_start, month_end + 1):
            months.append((year, month))  # Store as (year, month)

    return months
