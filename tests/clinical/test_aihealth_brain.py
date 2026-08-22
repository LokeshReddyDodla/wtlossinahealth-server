"""aihealth_brain.assess wrapper — no pin-copy, no invented coefficients."""

from __future__ import annotations

import json

import pytest

from lib.ai_foundation.clinical import aihealth_brain as brain


def _hypo_meal():
    return {
        "carb": 50,
        "protein": 10,
        "fiber": 5,
        "cal": 400,
        "pre": 55,
        "hour": 13,
    }


def _state_with_events():
    return {
        "history": [
            dict(
                carb=c,
                protein=10,
                fiber=5,
                cal=500,
                pre=110,
                hour=13,
                peak=0.45 * c + 4,
            )
            for c in (40, 55, 60, 70, 45, 50, 65, 38)
        ],
        "events": [{"peak_value": 70, "start_time": 1}],
        "cgm_summary": {
            "tir": 72,
            "cv": 30,
            "mean": 120,
            "postprandial_share": 0.62,
            "nocturnal_share": 0.18,
        },
    }


def test_public_import_path():
    from aihealth_brain import assess

    assert assess is brain.assess


def test_alias_recent_cgm_events_from_events():
    aliased = brain.alias_cgm_events({"events": [1, 2]})
    assert aliased["recent_cgm_events"] == [1, 2]
    assert aliased["events"] == [1, 2]


def test_alias_events_from_recent_cgm_events():
    aliased = brain.alias_cgm_events({"recent_cgm_events": [3]})
    assert aliased["events"] == [3]


def test_safety_does_not_leak_protein_first_levers(monkeypatch):
    """SAFETY must empty lever/levers even if the backend attached one."""

    def _leaky(_state, _meal):
        return {
            "output_mode": "SAFETY",
            "lever": {
                "name": "protein_first",
                "say": "start with the vegetables/dal, carbs last",
                "cite": "q1 meal sequencing",
            },
            "levers": [{"name": "protein_first"}],
            "bmiq": {
                "output_mode": "SAFETY_HOLD",
                "lever": {"name": "protein_first"},
            },
            "safety_flags": ["PRE_HYPO"],
            "prediction": {},
        }

    monkeypatch.setattr(brain, "_load_pin_assess", lambda: None)
    monkeypatch.setattr(brain, "_metabolic_assess", _leaky)

    out = brain.assess(_state_with_events(), _hypo_meal())
    assert out["output_mode"] == "SAFETY"
    assert out["lever"] is None
    assert out["levers"] == []
    assert out["bmiq"]["lever"] is None
    blob = json.dumps(out)
    assert "protein_first" not in blob


def test_safety_floor_exception_fail_closes(monkeypatch):
    def _boom(_state, _meal):
        raise RuntimeError("safety_floor rejected input")

    monkeypatch.setattr(brain, "_load_pin_assess", lambda: None)
    monkeypatch.setattr(brain, "_metabolic_assess", _boom)

    out = brain.assess({"events": []}, {"carb": 40, "pre": 70})
    assert out["output_mode"] == "SAFETY"
    assert out["lever"] is None
    assert "protein_first" not in json.dumps(out)
    assert "SAFETY_FLOOR" in out["safety_flags"]


def test_non_safety_exception_propagates(monkeypatch):
    def _boom(_state, _meal):
        raise ValueError("spike model missing")

    monkeypatch.setattr(brain, "_load_pin_assess", lambda: None)
    monkeypatch.setattr(brain, "_metabolic_assess", _boom)

    with pytest.raises(ValueError, match="spike model missing"):
        brain.assess({}, {"carb": 40})


def test_metabolic_port_hypo_is_safety_without_lever():
    """June engine on pre-hypo: SAFETY and no protein_first lever."""
    out = brain.assess(_state_with_events(), _hypo_meal())
    assert "PRE_HYPO" in (out.get("safety_flags") or [])
    assert out["output_mode"] == "SAFETY"
    assert not out.get("lever")
    assert "protein_first" not in json.dumps(out.get("lever") or {})
