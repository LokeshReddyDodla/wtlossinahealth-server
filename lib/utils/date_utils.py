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


def get_week_start_end(date: datetime, firstweekday=calendar.MONDAY):
    # Set the first weekday (e.g., Monday)
    calendar.setfirstweekday(firstweekday)

    # Find the start of the week
    start_of_week = date - timedelta(days=date.weekday())

    # Find the end of the week
    end_of_week = start_of_week + timedelta(days=6)

    return start_of_week, end_of_week
