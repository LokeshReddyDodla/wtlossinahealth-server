"""ProfileResolverService — the batch role-resolution layer behind inline
sender_profile on messages and participant profiles on chats.

Critical invariants:
- Three PG tables (patients / care_providers / admins) queried in parallel.
- Care-provider sub-roles ("Doctor", "Nurse", ...) flow through to ``subrole``;
  ``support_staff`` collapses into the top-level ``role`` with no subrole.
- Unknown ids get a synthesized "Unknown User" profile rather than missing
  keys — clients never need a fallback path.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

import lib.models  # noqa: F401,E402
from lib.models.patient import Patient  # noqa: F401,E402

from lib.services.chat.profile_resolver_service import (  # noqa: E402
    ProfileResolverService,
    _cp_role_split,
)


def _fake_session_returning(patients=None, care_providers=None, admins=None):
    """Build a fake session whose three select() calls return the three
    given lists in order. ProfileResolverService runs the queries in
    parallel via asyncio.gather, but each query gets its own .execute
    call, so we return based on the model in the where-clause."""
    patients = patients or []
    care_providers = care_providers or []
    admins = admins or []

    async def execute(stmt):
        compiled = str(stmt.compile())
        if "patients" in compiled.lower():
            rows = patients
        elif "care_providers" in compiled.lower():
            rows = care_providers
        elif "admins" in compiled.lower():
            rows = admins
        else:
            rows = []
        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=rows)
        result.scalars = MagicMock(return_value=scalars)
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute)
    return session


# --- _cp_role_split -----------------------------------------------------


def test_cp_role_split_support_staff_collapses_into_top_level():
    role, subrole = _cp_role_split("support_staff")
    assert role == "support_staff"
    assert subrole is None


def test_cp_role_split_support_staff_case_insensitive():
    role, subrole = _cp_role_split("Support_Staff")
    assert role == "support_staff"
    assert subrole is None


def test_cp_role_split_doctor_keeps_subrole():
    role, subrole = _cp_role_split("Doctor")
    assert role == "care_provider"
    assert subrole == "Doctor"


def test_cp_role_split_none_role_defaults_care_provider():
    role, subrole = _cp_role_split(None)
    assert role == "care_provider"
    assert subrole is None


def test_cp_role_split_empty_string_defaults_care_provider():
    role, subrole = _cp_role_split("")
    assert role == "care_provider"
    assert subrole is None


# --- resolve() end-to-end -----------------------------------------------


@pytest.mark.asyncio
async def test_resolve_patient_returns_patient_role():
    pid = uuid4()
    patient = SimpleNamespace(
        patient_id=pid,
        first_name="Alice",
        last_name="Singh",
        profile_picture="https://cdn/alice.jpg",
    )
    session = _fake_session_returning(patients=[patient])

    svc = ProfileResolverService()
    out = await svc.resolve.__wrapped__(
        svc, [str(pid)], postgres_session=session
    )

    profile = out[str(pid)]
    assert profile.role == "patient"
    assert profile.first_name == "Alice"
    assert profile.last_name == "Singh"
    assert profile.profile_picture == "https://cdn/alice.jpg"
    assert profile.subrole is None


@pytest.mark.asyncio
async def test_resolve_support_staff_collapses_to_top_level_enum():
    cpid = uuid4()
    cp = SimpleNamespace(
        care_provider_id=cpid,
        first_name="Priya",
        last_name="Shah",
        profile_picture=None,
        role="Support_Staff",  # mixed case — still collapses
    )
    session = _fake_session_returning(care_providers=[cp])

    svc = ProfileResolverService()
    out = await svc.resolve.__wrapped__(
        svc, [str(cpid)], postgres_session=session
    )

    profile = out[str(cpid)]
    assert profile.role == "support_staff"
    assert profile.subrole is None


@pytest.mark.asyncio
async def test_resolve_doctor_keeps_subrole():
    cpid = uuid4()
    cp = SimpleNamespace(
        care_provider_id=cpid,
        first_name="Vikram",
        last_name="Kumar",
        profile_picture=None,
        role="Doctor",
    )
    session = _fake_session_returning(care_providers=[cp])

    svc = ProfileResolverService()
    out = await svc.resolve.__wrapped__(
        svc, [str(cpid)], postgres_session=session
    )

    profile = out[str(cpid)]
    assert profile.role == "care_provider"
    assert profile.subrole == "Doctor"


@pytest.mark.asyncio
async def test_resolve_admin_returns_synthesized_support_team_name():
    aid = uuid4()
    admin = SimpleNamespace(id=aid)
    session = _fake_session_returning(admins=[admin])

    svc = ProfileResolverService()
    out = await svc.resolve.__wrapped__(
        svc, [str(aid)], postgres_session=session
    )

    profile = out[str(aid)]
    assert profile.role == "admin"
    assert profile.first_name == "Support"
    assert profile.last_name == "Team"


@pytest.mark.asyncio
async def test_resolve_unknown_id_synthesizes_unknown_user():
    """Critical: callers must never see a missing key. An unresolved id
    becomes a synthesized 'Unknown User' so clients render a generic
    avatar with no special-case code."""
    session = _fake_session_returning()

    svc = ProfileResolverService()
    out = await svc.resolve.__wrapped__(
        svc, ["never-seen"], postgres_session=session
    )

    profile = out["never-seen"]
    assert profile.first_name == "Unknown"
    assert profile.last_name == "User"
    assert profile.role == "patient"


@pytest.mark.asyncio
async def test_resolve_empty_input_returns_empty_dict():
    session = _fake_session_returning()
    svc = ProfileResolverService()
    out = await svc.resolve.__wrapped__(svc, [], postgres_session=session)
    assert out == {}


@pytest.mark.asyncio
async def test_resolve_dedups_repeated_ids():
    """Sending the same id 50 times in a message thread shouldn't trigger
    50 queries — input is deduped before the PG lookup."""
    pid = uuid4()
    patient = SimpleNamespace(
        patient_id=pid,
        first_name="Test",
        last_name="User",
        profile_picture=None,
    )
    session = _fake_session_returning(patients=[patient])

    svc = ProfileResolverService()
    repeated_ids = [str(pid)] * 50
    out = await svc.resolve.__wrapped__(
        svc, repeated_ids, postgres_session=session
    )

    assert len(out) == 1
    # PG was called exactly 3 times (patients, care_providers, admins).
    assert session.execute.await_count == 3


# --- support assistant (synthetic sender, no PG row) --------------------


@pytest.mark.asyncio
async def test_resolve_support_assistant_without_touching_pg():
    from lib.core.constants import SUPPORT_ASSISTANT_SENDER_ID

    session = _fake_session_returning()
    svc = ProfileResolverService()
    out = await svc.resolve.__wrapped__(
        svc, [SUPPORT_ASSISTANT_SENDER_ID], postgres_session=session
    )

    profile = out[SUPPORT_ASSISTANT_SENDER_ID]
    assert (profile.first_name, profile.last_name) == ("Support", "Assistant")
    assert profile.role == "admin"
    # Only the bot was requested: no role-table query should have run.
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_support_assistant_alongside_real_users():
    from lib.core.constants import SUPPORT_ASSISTANT_SENDER_ID

    pid = uuid4()
    patient = SimpleNamespace(
        patient_id=pid, first_name="Alice", last_name="Singh", profile_picture=None
    )
    session = _fake_session_returning(patients=[patient])
    svc = ProfileResolverService()
    out = await svc.resolve.__wrapped__(
        svc, [str(pid), SUPPORT_ASSISTANT_SENDER_ID], postgres_session=session
    )

    assert out[str(pid)].role == "patient"
    assert out[SUPPORT_ASSISTANT_SENDER_ID].last_name == "Assistant"
