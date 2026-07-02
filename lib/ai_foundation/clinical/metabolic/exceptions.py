"""Exception hierarchy for the metabolic clinical module."""


class MetabolicError(Exception):
    """Base exception for all metabolic engine errors."""


class AssemblerError(MetabolicError):
    """Failed to assemble patient state from data stores."""


class EngineError(MetabolicError):
    """Engine computation failed."""


class OutcomeError(MetabolicError):
    """Outcome tracking (advice logging / follow-up) failed."""
