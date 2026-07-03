"""Tests for MetabolicService.to_glucose_prediction — display semantics.

Locks the absolute-vs-rise contract that once silently broke: the engine's
rise delta was rendered by the app as an absolute peak ("your glucose after
this meal: 0-15 mg/dL"). Three-tier policy:

1. live_pre (measured CGM at meal time) → basis="absolute", anchored range
2. no live reading → basis="rise", delta range, no fabricated anchor
3. band width scales with confidence — a cold-start prediction may not
   claim the same precision as one learned from 20+ meals
"""

from __future__ import annotations

from unittest.mock import MagicMock

from lib.ai_foundation.clinical.metabolic.service import MetabolicService


def _service() -> MetabolicService:
    svc = MetabolicService.__new__(MetabolicService)  # mapping needs no deps
    return svc


def _contract(rise=3.0, confidence="moderate", observed=None, peak_minutes=60,
              show_number=True):
    return {
        "prediction": {
            "rise_mgdl": rise,
            "observed_mgdl": observed,
            "confidence": confidence,
            "n_meals_learned": 7,
        },
        "fact": "Expected rise about %s mg/dL." % rise,
        "lever": {},
        "v31": {
            "peak_minutes": peak_minutes,
            "show_number_to_patient": show_number,
            "confidence_tier": "moderate",
        },
    }


class TestAbsoluteTier:
    def test_live_pre_anchors_absolute(self):
        """Patient at 100, rise 3, moderate band ±12 → 100-115 absolute.

        The low is clamped at the anchor: a post-meal PEAK cannot sit below
        the measured pre-meal value, so uncertainty widens only upward.
        """
        raw = _service().to_glucose_prediction(_contract(rise=3.0), live_pre=100.0)
        assert raw["basis"] == "absolute"
        assert raw["pre_meal_mg_dl"] == 100
        assert raw["range_mg_dl_low"] == 100   # 100 + max(0, 3-12), clamped
        assert raw["range_mg_dl_high"] == 115  # 100 + 3 + 12
        # explicit delta always present alongside
        assert raw["rise_mg_dl_low"] == 0
        assert raw["rise_mg_dl_high"] == 15

    def test_absolute_never_below_anchor(self):
        """A meal can't be predicted to LOWER glucose below the measured
        pre-meal value via band arithmetic."""
        raw = _service().to_glucose_prediction(_contract(rise=2.0), live_pre=100.0)
        assert raw["range_mg_dl_low"] >= 100


class TestRiseTier:
    def test_no_live_reading_is_rise_semantics(self):
        """The exact bug from the app screenshot: rise 3 must be labeled a
        rise, never an absolute 0-15 'your glucose after this meal'."""
        raw = _service().to_glucose_prediction(_contract(rise=3.0))
        assert raw["basis"] == "rise"
        assert raw["pre_meal_mg_dl"] is None
        assert raw["range_mg_dl_low"] == 0
        assert raw["range_mg_dl_high"] == 15

    def test_range_mirrors_rise_when_basis_is_rise(self):
        """APP CONTRACT GUARANTEE: when basis == "rise", range_mg_dl_* is
        byte-identical to rise_mg_dl_* — the app may parse range_* alone
        and prefix "+". Locked here because the Flutter side relies on it."""
        for rise, conf in [(3.0, "moderate"), (30.0, "high"), (55.0, "cold-start")]:
            raw = _service().to_glucose_prediction(_contract(rise=rise, confidence=conf))
            assert raw["basis"] == "rise"
            assert raw["range_mg_dl_low"] == raw["rise_mg_dl_low"]
            assert raw["range_mg_dl_high"] == raw["rise_mg_dl_high"]

    def test_no_fabricated_anchor(self):
        """Without a measured reading there is no absolute claim at all."""
        raw = _service().to_glucose_prediction(_contract(rise=40.0))
        assert raw["basis"] == "rise"
        assert raw["pre_meal_mg_dl"] is None

    def test_prior_exposed_as_labeled_estimate_only(self):
        """The 90-day prior may inform the UI as context ('usually ~105 at
        this hour') but must never anchor the range."""
        c = _contract(rise=10.0)
        c["v31"]["pre_prior"] = {"value": 105.0, "provenance": "90d_prior"}
        raw = _service().to_glucose_prediction(c)
        assert raw["basis"] == "rise"                      # range stays delta
        assert raw["pre_meal_mg_dl"] is None               # no fake anchor
        assert raw["pre_meal_estimate_mg_dl"] == 105       # labeled context
        assert raw["pre_meal_estimate_source"] == "90d_prior"
        assert raw["range_mg_dl_high"] == 22               # 10+12, NOT 105-based

    def test_mean_prior_never_surfaces_as_time_estimate(self):
        """The flat 90-day mean is NOT time-of-day specific — surfacing it
        under 'usually around ~N at this time' copy would mislabel it."""
        c = _contract(rise=10.0)
        c["v31"]["pre_prior"] = {"value": 112.0, "provenance": "90d_mean"}
        raw = _service().to_glucose_prediction(c)
        assert raw["pre_meal_estimate_mg_dl"] is None
        assert raw["pre_meal_estimate_source"] is None

    def test_n_similar_meals_counts_evidence_not_training(self):
        """'Based on N similar meals' must count SIMILAR meals (evidence),
        not the model's total training count (n_meals_learned=7 here)."""
        c = _contract(rise=10.0)
        c["v31"]["evidence_meals"] = [
            {"date": "2026-06-01", "observed_peak": 150, "carbs": 60},
            {"date": "2026-06-10", "observed_peak": 145, "carbs": 55},
        ]
        raw = _service().to_glucose_prediction(c)
        assert raw["n_similar_meals"] == 2       # the similar ones
        assert raw["n_meals_learned"] == 7       # training count, separate field

    def test_measured_anchor_suppresses_estimate(self):
        """When a real reading exists, the estimate is redundant — omit it."""
        c = _contract(rise=10.0)
        c["v31"]["pre_prior"] = {"value": 105.0, "provenance": "90d_prior"}
        raw = _service().to_glucose_prediction(c, live_pre=100.0)
        assert raw["basis"] == "absolute"
        assert raw["pre_meal_estimate_mg_dl"] is None


class TestBandScalesWithConfidence:
    def test_high_confidence_tight_band(self):
        raw = _service().to_glucose_prediction(_contract(rise=30.0, confidence="high"))
        assert raw["rise_mg_dl_low"] == 22 and raw["rise_mg_dl_high"] == 38  # ±8

    def test_cold_start_wide_band(self):
        raw = _service().to_glucose_prediction(_contract(rise=30.0, confidence="cold-start"))
        assert raw["rise_mg_dl_low"] == 12 and raw["rise_mg_dl_high"] == 48  # ±18

    def test_observed_response_sensor_noise_only(self):
        """An already-measured response carries only sensor noise, not
        prediction uncertainty."""
        raw = _service().to_glucose_prediction(
            _contract(rise=30.0, observed=42.0, confidence="cold-start"),
        )
        assert raw["_kind"] == "observed"
        assert raw["rise_mg_dl_low"] == 37 and raw["rise_mg_dl_high"] == 47  # ±5


class TestGates:
    def test_no_rise_returns_none(self):
        raw = _service().to_glucose_prediction({"prediction": {}, "v31": {}})
        assert raw is None

    def test_show_number_gate_passthrough(self):
        raw = _service().to_glucose_prediction(_contract(show_number=False))
        assert raw["_show_number"] is False  # caller suppresses + falls back
