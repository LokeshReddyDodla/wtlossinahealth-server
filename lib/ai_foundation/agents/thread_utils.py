"""
Thread ID utilities — single source of truth for thread ID generation.

All thread IDs in the foundation use these functions. No other code
should construct thread IDs manually.

Convention:
    Patient:              bot:patient:{patient_id}
    Provider + 1 patient: bot:provider:{provider_id}:patient:{patient_id}
    Provider + N patients: bot:provider:{provider_id}:group:{hash}
    Admin + 1 patient:    bot:admin:{admin_id}:patient:{patient_id}
    Admin + N patients:   bot:admin:{admin_id}:group:{hash}
    Admin + 0 patients:   bot:admin:{admin_id}:general

Thread list prefix (for querying all threads for a user):
    Patient:       bot:patient:{id}
    Care Provider: bot:provider:{id}
    Admin:         bot:admin:{id}
"""

from __future__ import annotations

import hashlib


def resolve_thread_id(
    *,
    role: str,
    actor_id: str,
    patient_ids: list[str] | None = None,
) -> str:
    """Generate a thread ID from role + actor + patients.

    Args:
        role: "patient", "care_provider", or "admin"
        actor_id: The authenticated user's ID
        patient_ids: List of patient IDs being queried

    Returns:
        Deterministic thread ID string.
    """
    prefix = _role_prefix(role)
    pids = patient_ids or []

    if role == "patient":
        return f"bot:patient:{actor_id}"

    if len(pids) == 1:
        return f"bot:{prefix}:{actor_id}:patient:{pids[0]}"

    if len(pids) > 1:
        group_key = hashlib.sha256(
            ":".join(sorted(pids)).encode()
        ).hexdigest()[:12]
        return f"bot:{prefix}:{actor_id}:group:{group_key}"

    # 0 patients (admin only — general platform questions)
    return f"bot:{prefix}:{actor_id}:general"


def thread_prefix_for_user(*, role: str, actor_id: str) -> str:
    """Get the thread ID prefix for listing all threads for a user.

    Used in MongoDB regex queries to find all threads belonging to a user.
    """
    prefix = _role_prefix(role)
    return f"bot:{prefix}:{actor_id}"


def _role_prefix(role: str) -> str:
    """Map role string to thread ID prefix.

    care_provider → provider (shorter, matches legacy convention)
    everything else → as-is
    """
    if role == "care_provider":
        return "provider"
    return role
