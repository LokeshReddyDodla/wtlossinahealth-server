from datetime import date, datetime, timezone

from lib.ai_foundation.agents.proactive_monitor.scheduling import DEFAULT_TIMEZONE
from lib.services.gamification.time_utils import (
    local_today,
    matches_local_hour,
    naive_day_bounds_for_local_date,
    resolve_timezone_name,
)


class TestGamificationTimeUtils:
    def test_invalid_timezone_falls_back_to_default(self):
        assert resolve_timezone_name("Not/A_Real_Timezone") == DEFAULT_TIMEZONE

    def test_local_today_and_hour_use_patient_timezone(self):
        now = datetime(2026, 4, 3, 0, 30, tzinfo=timezone.utc)

        assert local_today("America/New_York", now=now) == date(2026, 4, 2)
        assert matches_local_hour("America/New_York", 20, now=now) is True

    def test_naive_day_bounds_convert_local_day_to_naive_utc(self):
        start_utc, end_utc = naive_day_bounds_for_local_date(
            date(2026, 4, 3),
            "Asia/Kolkata",
        )

        assert start_utc == datetime(2026, 4, 2, 18, 30)
        assert end_utc == datetime(2026, 4, 3, 18, 29, 59, 999999)
