"""
Metabolic clinical module — glucose prediction, meal attribution, body composition,
coaching nudges, and safety gating. Pure Python stdlib, deterministic, zero runtime deps.

Agents use MetabolicService (service.py), never the raw engine.
"""

from .engine import MetabolicEngine
from .enrichment import enrich
from .lenses import apply_lenses
from .data_sufficiency import assess_readiness
from .nudge import build_nudges
from .render import build_prompt

__all__ = [
    "MetabolicEngine",
    "MetabolicService",
    "enrich",
    "apply_lenses",
    "assess_readiness",
    "build_nudges",
    "build_prompt",
]


def __getattr__(name):
    if name == "MetabolicService":
        from .service import MetabolicService
        return MetabolicService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
