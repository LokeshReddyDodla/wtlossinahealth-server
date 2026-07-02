"""Pure-stdlib metabolic engine tests — no DB, no network, no fixtures."""
import pytest

from lib.ai_foundation.clinical.metabolic.engine import MetabolicEngine
from lib.ai_foundation.clinical.metabolic.enrichment import enrich
from lib.ai_foundation.clinical.metabolic.lenses import apply_lenses


# -- fixtures --

def _history(n=20):
    return [
        dict(carb=c, protein=10, fiber=5, cal=500, pre=110, hour=13, peak=0.45 * c + 4)
        for c in [40, 55, 60, 70, 45, 50, 65, 38, 42, 58, 63, 47, 52, 68, 44, 57, 62, 48, 53, 67][:n]
    ]


def _patient_state(n_meals=20, tir=72, cv=30, mean=120):
    return {
        "history": _history(n_meals),
        "cgm_summary": {
            "tir": tir, "cv": cv, "mean": mean,
            "postprandial_share": 0.62, "nocturnal_share": 0.18,
        },
    }


def _high_carb_meal():
    return {"carb": 95, "protein": 8, "fiber": 2, "cal": 640, "pre": 120, "hour": 13}


def _balanced_meal():
    return {"carb": 35, "protein": 25, "fiber": 8, "cal": 420, "pre": 100, "hour": 13}


@pytest.fixture
def engine():
    return MetabolicEngine()


# -- engine core --

class TestEngineAssess:
    def test_high_carb_suggests(self, engine):
        contract = engine.assess(_patient_state(), _high_carb_meal())
        assert contract["output_mode"] == "SUGGEST"
        assert contract["prediction"]["rise_mgdl"] > 30
        assert contract["lever"]["cite"]

    def test_balanced_meal_reinforces(self, engine):
        contract = engine.assess(_patient_state(), _balanced_meal())
        assert contract["output_mode"] in ("REINFORCE", "STATE_FACTS")

    def test_cold_start_fewer_meals(self, engine):
        contract = engine.assess(_patient_state(n_meals=2), _high_carb_meal())
        pr = contract["prediction"]
        assert pr["confidence"] in ("cold-start", "moderate")
        assert pr["n_meals_learned"] <= 2

    def test_prediction_has_required_keys(self, engine):
        contract = engine.assess(_patient_state(), _high_carb_meal())
        pr = contract["prediction"]
        for k in ("rise_mgdl", "predicted_mgdl", "source", "confidence", "n_meals_learned"):
            assert k in pr, f"missing prediction key: {k}"

    def test_attribution_decomposes(self, engine):
        contract = engine.assess(_patient_state(), _high_carb_meal())
        attr = contract["attribution"]
        assert attr["label"] in ("MEAL_DRIVEN", "PHYSIOLOGY_DRIVEN", "MIXED", "IN_RANGE", "INSUFFICIENT_HISTORY")
        assert "carb_component_mgdl" in attr

    def test_zero_carb_no_crash(self, engine):
        meal = {"carb": 0, "protein": 30, "fiber": 10, "cal": 300, "pre": 100, "hour": 13}
        contract = engine.assess(_patient_state(), meal)
        assert contract["prediction"]["rise_mgdl"] >= 0

    def test_safety_pre_hypo(self, engine):
        meal = {"carb": 50, "protein": 10, "fiber": 5, "cal": 400, "pre": 55, "hour": 13}
        contract = engine.assess(_patient_state(), meal)
        assert "PRE_HYPO" in contract.get("safety_flags", [])


# -- enrichment --

class TestEnrichment:
    def test_confidence_tier_high(self, engine):
        ps = _patient_state(n_meals=20)
        contract = engine.assess(ps, _high_carb_meal())
        enriched = enrich(contract, ps, _high_carb_meal(), live_pre=120)
        assert enriched["v31"]["confidence_tier"] == "high"

    def test_confidence_tier_moderate(self, engine):
        ps = _patient_state(n_meals=8)
        contract = engine.assess(ps, _high_carb_meal())
        enriched = enrich(contract, ps, _high_carb_meal(), live_pre=120)
        assert enriched["v31"]["confidence_tier"] == "moderate"

    def test_has_cgm_flag(self, engine):
        ps = _patient_state()
        contract = engine.assess(ps, _high_carb_meal())
        enriched = enrich(contract, ps, _high_carb_meal(), live_pre=120)
        assert enriched["v31"]["has_cgm"] is True

    def test_no_cgm_summary(self, engine):
        ps = _patient_state()
        ps.pop("cgm_summary")
        contract = engine.assess(ps, _high_carb_meal())
        enriched = enrich(contract, ps, _high_carb_meal())
        assert enriched["v31"]["has_cgm"] is False


# -- lenses --

class TestLenses:
    def test_all_five_lenses_present(self):
        ps = _patient_state()
        result = apply_lenses(ps)
        for lens in ("overnight_gv", "hepatic_dawn", "ir_phenotype", "day_burden", "people_like_you"):
            assert lens in result, f"missing lens: {lens}"

    def test_empty_state_no_crash(self):
        result = apply_lenses({})
        assert isinstance(result, dict)
        assert len(result) >= 5


# -- contracts (needs pydantic, but no DB) --

class TestContracts:
    def test_engine_contract_validates(self, engine):
        from lib.ai_foundation.clinical.metabolic.contracts import EngineContract
        ps = _patient_state()
        contract = engine.assess(ps, _high_carb_meal())
        contract = enrich(contract, ps, _high_carb_meal(), live_pre=120)
        contract["lenses"] = apply_lenses(ps)
        ec = EngineContract.model_validate(contract)
        assert ec.output_mode == "SUGGEST"
        assert ec.prediction.rise_mgdl > 0

    def test_roundtrip(self, engine):
        from lib.ai_foundation.clinical.metabolic.contracts import EngineContract
        ps = _patient_state()
        contract = engine.assess(ps, _high_carb_meal())
        contract = enrich(contract, ps, _high_carb_meal(), live_pre=120)
        contract["lenses"] = apply_lenses(ps)
        ec = EngineContract.model_validate(contract)
        d = ec.model_dump()
        assert d["prediction"]["rise_mgdl"] == ec.prediction.rise_mgdl


# -- outcome mapping (pure function, lazy import to avoid DB chain) --

class TestAdviceEventMapping:
    def _map(self):
        pytest.importorskip("asyncpg")
        from lib.ai_foundation.clinical.metabolic.outcome import advice_event_from_contract
        return advice_event_from_contract

    def test_suggest_with_cite_maps(self, engine):
        fn = self._map()
        contract = engine.assess(_patient_state(), _high_carb_meal())
        event = fn(contract, "patient-1", "glucose", "lunch_suggest")
        assert event is not None
        assert event["patient_id"] == "patient-1"
        assert event["lever_name"] == contract["lever"]["name"]

    def test_non_suggest_returns_none(self, engine):
        fn = self._map()
        contract = engine.assess(_patient_state(), _balanced_meal())
        if contract["output_mode"] != "SUGGEST":
            event = fn(contract, "patient-1", "glucose", "lunch_suggest")
            assert event is None

    def test_no_cite_returns_none(self):
        fn = self._map()
        contract = {"output_mode": "SUGGEST", "lever": {"name": "test", "say": "do x"}, "prediction": {}}
        event = fn(contract, "p1", "glucose", "test")
        assert event is None


# -- nudges (imports settings which needs pydantic_settings) --

class TestNudges:
    def _build(self):
        from lib.ai_foundation.clinical.metabolic.nudge import build_nudges
        return build_nudges

    def test_suggest_fires_spike_nudge(self, engine):
        build_nudges = self._build()
        contract = engine.assess(_patient_state(), _high_carb_meal())
        nudges = build_nudges(contract=contract)
        triggers = [n["trigger"] for n in nudges]
        assert "predicted_spike" in triggers

    def test_safety_always_survives_cap(self):
        build_nudges = self._build()
        contract = {"output_mode": "SAFETY", "lever": {}, "attribution": {}}
        nudges = build_nudges(contract=contract)
        assert any(n["trigger"] == "safety" for n in nudges)

    def test_max_cap(self, engine):
        build_nudges = self._build()
        contract = engine.assess(_patient_state(), _high_carb_meal())
        nudges = build_nudges(contract=contract, cgm_age_days=5, signals={"cold_start": True})
        assert len(nudges) <= 2

    def test_cold_start_nudge(self):
        build_nudges = self._build()
        nudges = build_nudges(signals={"cold_start": True})
        assert any(n["trigger"] == "cold_start" for n in nudges)


# -- full pipeline integration (still no DB) --

class TestFullPipeline:
    def test_assess_enrich_lenses_contract(self, engine):
        from lib.ai_foundation.clinical.metabolic.contracts import EngineContract
        ps = _patient_state()
        meal = _high_carb_meal()
        contract = engine.assess(ps, meal)
        contract = enrich(contract, ps, meal, live_pre=120)
        contract["lenses"] = apply_lenses(ps)
        ec = EngineContract.model_validate(contract)
        assert ec.output_mode == "SUGGEST"
        assert ec.v31.has_cgm is True
        assert ec.v31.confidence_tier == "high"
        assert ec.lenses.overnight_gv is not None
