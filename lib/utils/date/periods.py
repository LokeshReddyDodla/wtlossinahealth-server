from datetime import datetime, timedelta
from typing import List, Dict


class DayWisePeriod:
    def __init__(self, start_date: datetime, end_date: datetime):
        self.periods = self.split_into_days(start_date, end_date)

    @staticmethod
    def split_into_days(
        start_date: datetime, end_date: datetime
    ) -> List[Dict[str, datetime]]:
        days = []
        current_date = start_date
        while current_date <= end_date:
            days.append(
                {
                    "date": current_date.strftime("%Y-%m-%d"),
                    "from_date": current_date,
                    "to_date": current_date + timedelta(days=1),
                }
            )
            current_date += timedelta(days=1)
        return days


class WeekWisePeriod:
    def __init__(self, start_date: datetime, end_date: datetime):
        self.periods = self.split_into_weeks(start_date, end_date)

    @staticmethod
    def split_into_weeks(
        start_date: datetime, end_date: datetime
    ) -> List[Dict[str, datetime]]:
        weeks = []
        current_date = start_date
        week_no = 1
        while current_date <= end_date:
            week_end_date = current_date + timedelta(days=6)
            if week_end_date > end_date:
                week_end_date = end_date
            weeks.append(
                {
                    "week_no": week_no,
                    "from_date": current_date,
                    "to_date": week_end_date,
                }
            )
            current_date += timedelta(days=7)
            week_no += 1
        return weeks


class OverallPeriod:
    def __init__(self, start_date: datetime, end_date: datetime):
        self.periods = [{"from_date": start_date, "to_date": end_date}]
