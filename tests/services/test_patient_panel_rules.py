"""Rule engine tests for the patient panel signal.

The rules are pure and deterministic, so this covers the full matrix: each
assessment band, the condition-aware (pregnancy) thresholds, modality handling
(a weight-only patient is not a glucose gap), rule ordering (most-severe wins),
and reason templating.
"""

from lib.schemas.patient_panel_signal import (
    GlucoseSource,
    Modality,
    PanelAssessment,
    PanelInputs,
)
from lib.services.patient_panel.compute import build_signal
from lib.services.patient_panel.rules import classify


def mk(**kw) -> PanelInputs:
    kw.setdefault("has_any_data", True)
    return PanelInputs(**kw)


# ── not started ────────────────────────────────────────────────────────────
def test_never_any_data_is_not_started():
    r = classify(PanelInputs(has_any_data=False))
    assert r.assessment is PanelAssessment.NOT_STARTED
    assert r.priority == 40


# ── stale CGM readings → data gap (honest: missing data, not a broken sync) ──
def test_stale_cgm_is_data_gap_not_a_sync_claim():
    r = classify(mk(glucose_sync_stale=True, glucose_sync_stale_days=8))
    assert r.assessment is PanelAssessment.DATA_GAP
    assert "No recent CGM" in r.reason and "8d" in r.reason
    assert "syncing" not in r.reason
    assert r.priority == 30  # below watch, not above it


# ── at risk ────────────────────────────────────────────────────────────────
def test_nocturnal_hypo_is_at_risk():
    r = classify(mk(nocturnal_below_70_pct=41, tir_pct=78))
    assert r.assessment is PanelAssessment.AT_RISK
    assert "Nocturnal hypo 41%" in r.reason
    assert r.priority == 0


def test_severe_lows_is_at_risk():
    r = classify(mk(below_54_pct=2.4))
    assert r.assessment is PanelAssessment.AT_RISK
    assert "<54" in r.reason


def test_high_a1c_is_at_risk():
    r = classify(mk(a1c=10.5, fasting_glucose=221))
    assert r.assessment is PanelAssessment.AT_RISK
    assert "A1c 10.5%" in r.reason


def test_very_low_tir_is_at_risk():
    r = classify(mk(tir_pct=45))
    assert r.assessment is PanelAssessment.AT_RISK


# ── data gap ───────────────────────────────────────────────────────────────
def test_stale_glucose_is_data_gap():
    r = classify(mk(last_glucose_days_ago=30, glucose_reading_count_14d=0))
    assert r.assessment is PanelAssessment.DATA_GAP
    assert "Logging stopped" in r.reason  # ≥ disengaged_days


def test_recent_but_stale_glucose_gap_wording():
    r = classify(mk(last_glucose_days_ago=16, glucose_reading_count_14d=1))
    assert r.assessment is PanelAssessment.DATA_GAP
    assert "16d" in r.reason


def test_sparse_readings_is_data_gap():
    r = classify(mk(glucose_reading_count_14d=3, last_glucose_days_ago=5))
    assert r.assessment is PanelAssessment.DATA_GAP
    assert "3 readings" in r.reason


# ── watch ──────────────────────────────────────────────────────────────────
def test_below_target_tir_is_watch():
    r = classify(mk(tir_pct=62))
    assert r.assessment is PanelAssessment.WATCH
    assert "TIR 62%" in r.reason


def test_high_fasting_is_watch():
    r = classify(mk(fasting_glucose=175, smbg_avg=118))
    assert r.assessment is PanelAssessment.WATCH
    assert "Fasting 175" in r.reason


def test_high_smbg_avg_is_watch():
    r = classify(mk(smbg_avg=152))
    assert r.assessment is PanelAssessment.WATCH
    assert "SMBG avg 152" in r.reason


def test_a1c_between_watch_and_high_is_watch():
    r = classify(mk(a1c=7.8))
    assert r.assessment is PanelAssessment.WATCH


def test_activity_drop_is_watch():
    r = classify(mk(activity_dropping=True, activity_note="steps 2,348→175"))
    assert r.assessment is PanelAssessment.WATCH
    assert "steps 2,348→175" in r.reason


def test_worsening_tir_trend_is_watch():
    r = classify(mk(tir_pct=72, tir_delta=-6))
    assert r.assessment is PanelAssessment.WATCH
    assert "slipping" in r.reason


# ── responding ─────────────────────────────────────────────────────────────
def test_high_tir_is_responding():
    r = classify(mk(tir_pct=96, tir_delta=3, below_54_pct=0))
    assert r.assessment is PanelAssessment.RESPONDING
    assert "TIR 96%" in r.reason
    assert r.priority == 50


def test_weight_only_patient_is_responding_not_gap():
    # A non-diabetic weight-loss patient has no glucose — that is not a data gap.
    r = classify(mk(glucose_expected=False, weight_delta_kg=-6.4, glucose_reading_count_14d=0))
    assert r.assessment is PanelAssessment.RESPONDING
    assert "-6.4 kg" in r.reason


# ── condition-aware (pregnancy tightens targets) ───────────────────────────
def test_pregnancy_tir_target_is_stricter():
    preg = classify(mk(is_pregnant=True, tir_pct=80))
    std = classify(mk(is_pregnant=False, tir_pct=80))
    assert preg.assessment is PanelAssessment.WATCH  # below 90 target
    assert std.assessment is PanelAssessment.RESPONDING  # above 70 target


def test_pregnancy_nocturnal_hypo_more_sensitive():
    # 4% nocturnal lows: at-risk in pregnancy (threshold 3), not standard (5).
    assert classify(mk(is_pregnant=True, nocturnal_below_70_pct=4)).assessment is PanelAssessment.AT_RISK
    assert classify(mk(is_pregnant=False, nocturnal_below_70_pct=4)).assessment is not PanelAssessment.AT_RISK


# ── rule ordering: most severe wins ────────────────────────────────────────
def test_hypo_danger_outranks_below_target_tir():
    # Both a low TIR (watch) and nocturnal hypo (at-risk) present → at-risk.
    r = classify(mk(tir_pct=65, nocturnal_below_70_pct=12))
    assert r.assessment is PanelAssessment.AT_RISK


# ── build_signal echoes metrics + classification onto the row ──────────────
def test_build_signal_composes_row():
    sig = build_signal(
        patient_id="p1", name="Sunita Menon", age=52, sex="F",
        conditions=["T2D 8y", "HTN"], modality=Modality.CGM,
        facility_id="f1", care_provider_ids=["cp1"],
        inputs=mk(nocturnal_below_70_pct=41, tir_pct=78, gmi=7.0, cv_pct=34),
        last_glucose_source=GlucoseSource.CGM,
    )
    assert sig.assessment is PanelAssessment.AT_RISK
    assert sig.priority == 0
    assert sig.tir_pct == 78 and sig.gmi == 7.0 and sig.cv_pct == 34
    assert sig.modality is Modality.CGM
    assert sig.care_provider_ids == ["cp1"]
    assert sig.computed_at is not None
