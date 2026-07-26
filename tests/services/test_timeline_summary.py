"""Day-summary aggregation (the dashboard strip) + heart-rate de-noising.

  * continuous heart_rate never becomes feed events (it floods otherwise)
  * fitness_data / vitals_data rows aggregate into the right DaySummary fields
"""

import asyncio
from datetime import date

from lib.services.patient_timeline_service import PatientTimelineService


class _FakeClient:
    """Canned rows per query, matched by a substring of the SQL."""

    def __init__(self, by_marker):
        self._by_marker = by_marker

    def execute(self, query):
        for marker, rows in self._by_marker.items():
            if marker in query:
                return rows
        return []


class _FakeCH:
    def __init__(self, client):
        self.client = client


def _svc(client):
    return PatientTimelineService(
        postgres_store=None, clickhouse_store=_FakeCH(client), insight_tracker=None,
        cgm_report_service=None, meal_report_service=None,
        fitness_report_service=None, sleep_report_service=None,
    )


def test_day_summary_aggregates_activity_and_vitals():
    client = _FakeClient({
        "fitness_data": [
            ("STEPS", 8240.0),
            ("ACTIVE_ENERGY_BURNED", 430.4),
            ("DISTANCE_WALKING_RUNNING", 4120.0),  # metres → 4.12 km
        ],
        "vitals_data": [
            ("heart_rate", 66.3, 57.0, 142.0, 71.0),
            ("resting_heart_rate", 58.0, 58.0, 60.0, 58.0),
            ("blood_oxygen", 97.6, 95.0, 99.0, 98.0),
        ],
    })
    s = asyncio.run(_svc(client)._get_day_summary("p1", date(2026, 7, 25)))
    assert s.steps == 8240
    assert s.active_energy_kcal == 430.4
    assert s.distance_km == 4.12
    assert s.avg_hr == 66 and s.min_hr == 57 and s.max_hr == 142
    assert s.resting_hr == 58
    assert s.avg_spo2 == 97.6


def test_vital_events_drop_heart_rate_but_keep_spot_readings():
    client = _FakeClient({
        "vitals_data": [
            ("heart_rate", 61.0, "2026-07-25T06:09:00"),
            ("resting_heart_rate", 58.0, "2026-07-25T06:00:00"),
            ("blood_oxygen", 98.0, "2026-07-25T07:00:00"),
            ("weight", 74.2, "2026-07-25T07:05:00"),
        ],
    })
    events = asyncio.run(_svc(client)._get_vital_events("p1", date(2026, 7, 25)))
    types = {e.data.get("vital_type") for e in events}
    assert "heart_rate" not in types and "resting_heart_rate" not in types
    assert types == {"blood_oxygen", "weight"}
    spo2 = next(e for e in events if e.data["vital_type"] == "blood_oxygen")
    assert "%" in spo2.title


if __name__ == "__main__":
    test_day_summary_aggregates_activity_and_vitals()
    test_vital_events_drop_heart_rate_but_keep_spot_readings()
    print("timeline summary + de-noise checks passed")
