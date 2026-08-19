"""Timeline summary + de-noise, now derived (no per-request summary queries).

  * _build_vital_events drops the continuous HR stream, keeps spot readings
  * _build_summary derives the strip from data the feed already fetched:
      - steps/active from the fitness REPORT (matches Home; not a raw CH sum)
      - HR/SpO2 aggregated from the vitals rows
      - glucose from the CGM report (shows on a fully in-range day)
"""

from datetime import datetime

from lib.services.patient_timeline_service import PatientTimelineService


def _svc():
    return PatientTimelineService(
        postgres_store=None, clickhouse_store=None, insight_tracker=None,
        cgm_report_service=None, meal_report_service=None,
        fitness_report_service=None, sleep_report_service=None,
    )


def test_summary_derived_from_reports_and_rows():
    svc = _svc()
    # (type, value, time) — same shape _fetch_vitals_rows returns.
    vitals_rows = [
        ("heart_rate", 60.0, datetime(2026, 7, 25, 8, 5)),
        ("heart_rate", 72.0, datetime(2026, 7, 25, 8, 40)),  # hour 8 → avg 66
        ("heart_rate", 90.0, datetime(2026, 7, 25, 9, 10)),  # hour 9 → 90
        ("resting_heart_rate", 58.0, datetime(2026, 7, 25, 6, 0)),
        ("blood_oxygen", 97.0, datetime(2026, 7, 25, 7, 0)),
        ("blood_oxygen", 99.0, datetime(2026, 7, 25, 7, 30)),
    ]
    fitness_report = {"steps": 27696, "active_energy": 430.4}
    cgm_report = {
        "cgm_summary_stats": {"average_glucose_mgdl": 117.2},
        "cgm_range_stats": {"in_target_70_180_percent": 100.0},
    }

    s = svc._build_summary(vitals_rows, fitness_report, cgm_report)

    # steps/active from the report, NOT a raw ClickHouse sum
    assert s.steps == 27696
    assert s.active_energy_kcal == 430.4
    # HR aggregated from the same rows the feed used
    assert s.avg_hr == 74 and s.min_hr == 60 and s.max_hr == 90
    assert s.resting_hr == 58
    assert s.avg_spo2 == 98.0
    # glucose present even though a 100%-in-range day fires no glucose events
    assert s.avg_glucose == 117
    assert s.time_in_range == 100.0
    # sleep is set by the caller from the checkin, not _build_summary
    assert s.sleep_hours is None


def test_summary_empty_when_no_sources():
    s = _svc()._build_summary([], None, None)
    assert s.steps is None and s.avg_hr is None and s.avg_glucose is None


def test_vital_events_drop_heart_rate_keep_spot_readings():
    rows = [
        ("heart_rate", 61.0, "2026-07-25T06:09:00"),
        ("resting_heart_rate", 58.0, "2026-07-25T06:00:00"),
        ("blood_oxygen", 98.0, "2026-07-25T07:00:00"),
        ("weight", 74.2, "2026-07-25T07:05:00"),
    ]
    events = _svc()._build_vital_events(rows)
    types = {e.data.get("vital_type") for e in events}
    assert "heart_rate" not in types and "resting_heart_rate" not in types
    assert types == {"blood_oxygen", "weight"}
    spo2 = next(e for e in events if e.data["vital_type"] == "blood_oxygen")
    assert "%" in spo2.title


if __name__ == "__main__":
    test_summary_derived_from_reports_and_rows()
    test_summary_empty_when_no_sources()
    test_vital_events_drop_heart_rate_keep_spot_readings()
    print("timeline summary (derived) checks passed")
