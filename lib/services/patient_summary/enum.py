from enum import Enum


class StaleReason(str, Enum):
    """Reasons why a summary became stale."""

    DATA_UPDATED = (
        "data_updated"  # Any report data changed (CGM, meals, activity, sleep, vitals)
    )
    DATA_DELETED = "data_deleted"  # Data was removed
    MANUAL_INVALIDATION = "manual_invalidation"  # Admin/system forced stale


class SummaryState(str, Enum):
    """Patient summary lifecycle states."""

    GENERATING = "generating"  # Initial generation in progress
    FINALIZED = "finalized"  # Successfully generated and current
    STALE = "stale"  # Data updated, needs regeneration
    FAILED = "failed"  # Generation failed


class RegeneratedBy(str, Enum):
    """Who triggered the generation/regeneration."""

    SYSTEM_INITIAL = "system_initial"  # First time generation by system
    SYSTEM = "system"  # Nightly job regeneration
    USER = "user"  # User clicked regenerate
    ADMIN = "admin"  # Admin forced regeneration
