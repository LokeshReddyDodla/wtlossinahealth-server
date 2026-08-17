"""Pure context composition (_build) tests — the DB reads are thin; the mapping
of profile fields into the panel context is what's worth testing."""

from datetime import date, datetime, timezone

from lib.schemas.patient_panel_signal import GlucoseSource, Modality
from lib.services.patient_panel.context import _build

_NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)


def _b(**kw):
    base = dict(
        first_name="Raj", last_name="Ramanand", dob=date(1962, 1, 1), gender="M",
        weight_kg=72.0, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        diabetes_type="T2D", diabetes_years=10, is_pregnant=False, pregnancy_weeks=None,
        care_provider_ids=["cp1"], facility_id="f1",
        frontier_at=None, frontier_source=GlucoseSource.NONE, now=_NOW,
    )
    base.update(kw)
    return _build(**base)


def test_identity_and_conditions():
    c = _b()
    assert c["name"] == "Raj Ramanand"
    assert c["age"] == 64
    assert c["conditions"] == ["T2D 10y"]
    assert c["glucose_expected"] is True


def test_cgm_patient_recent_frontier_is_cgm_not_stale():
    c = _b(frontier_at=datetime(2026, 8, 17, tzinfo=timezone.utc), frontier_source=GlucoseSource.CGM)
    assert c["modality"] is Modality.CGM
    assert c["glucose_sync_stale"] is False
    assert c["last_glucose_days_ago"] == 0


def test_connected_but_stale_sensor_flags_sync():
    c = _b(frontier_at=datetime(2026, 8, 9, tzinfo=timezone.utc), frontier_source=GlucoseSource.CGM)
    assert c["glucose_sync_stale"] is True  # 8 days, within the 2–14 window
    assert c["glucose_sync_stale_days"] == 8


def test_long_gap_is_not_sync_stale_but_a_data_gap():
    c = _b(frontier_at=datetime(2026, 7, 1, tzinfo=timezone.utc), frontier_source=GlucoseSource.CGM)
    assert c["glucose_sync_stale"] is False  # >14 days → plain gap, not "not syncing"
    assert c["last_glucose_days_ago"] > 14


def test_pregnant_gdm_patient():
    c = _b(diabetes_type="GDM", diabetes_years=None, is_pregnant=True, pregnancy_weeks=26)
    assert c["is_pregnant"] is True
    assert c["conditions"][0] == "GDM 26wk"


def test_weight_only_non_diabetic():
    c = _b(diabetes_type=None, diabetes_years=None, weight_kg=80.0)
    assert c["glucose_expected"] is False
    assert c["modality"] is Modality.WEIGHT
    assert c["conditions"] == []
