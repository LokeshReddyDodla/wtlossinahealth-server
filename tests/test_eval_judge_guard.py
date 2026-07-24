"""Deterministic fabrication guard on the eval judge.

A number present in the fixture data can never be a fabrication; the guard
spares grounded figures from a spurious LLM-judge flag without ever clearing
a real fabrication (which cites numbers absent from the data).
"""

from evals.judge import _strip_grounded_fabrications as strip

_GROUNDED = "CGM daily summary: average glucose 148 mg/dL, TIR 72%. Steps 6500."


def test_grounded_number_cleared():
    assert strip(["average glucose was 148 mg/dL"], _GROUNDED) == []


def test_ungrounded_number_kept():
    assert strip(["blood pressure was 120/80"], _GROUNDED) == ["blood pressure was 120/80"]
    assert strip(["slept 7 hours"], _GROUNDED) == ["slept 7 hours"]


def test_mixed_keeps_only_ungrounded():
    assert strip(["148 mg/dL", "slept 7 hours"], _GROUNDED) == ["slept 7 hours"]


def test_numberless_claim_kept():
    # Can't be verified by number, so the LLM's flag stands.
    assert strip(["invented a medication"], _GROUNDED) == ["invented a medication"]
