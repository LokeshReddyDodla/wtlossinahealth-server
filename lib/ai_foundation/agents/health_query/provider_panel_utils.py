"""Pure helpers for provider panel access handling."""


def has_partial_access(requested_count: int, accessible_count: int) -> bool:
    """Return True when a care provider requested patients they cannot access."""
    return accessible_count != requested_count
