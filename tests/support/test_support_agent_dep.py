"""Tests for the support-agent auth dependency.

This dep is the *only* authorization boundary for the entire
``/v1/admin/support_tickets/*`` surface — it must:
- accept active Admins (product scope)
- accept CareProviders with role=support_staff and a facility (facility scope)
- reject inactive admins
- reject CareProviders without role=support_staff
- reject CareProviders without a facility
- reject patients
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

# Warm up the import graph.
import lib.models  # noqa: F401,E402
from lib.models.patient import Patient  # noqa: F401,E402

from lib.core.constants import ProfileTypeEnum  # noqa: E402
from lib.dependencies.auth.support_agent import (  # noqa: E402
    SupportAgent,
    get_support_agent_actor,
)


def _session_returning(model):
    """Build a fake AsyncSession whose .execute returns a result whose
    .scalars().first() yields ``model``."""
    scalars = MagicMock()
    scalars.first = MagicMock(return_value=model)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_active_admin_gets_product_scope():
    admin_id = uuid4()
    admin = SimpleNamespace(id=admin_id, is_active=True)
    session = _session_returning(admin)

    actor = await get_support_agent_actor(
        request=MagicMock(),
        token_data=(str(admin_id), ProfileTypeEnum.ADMIN.value),
        session=session,
    )

    assert isinstance(actor, SupportAgent)
    assert actor.role == ProfileTypeEnum.ADMIN
    assert actor.allowed_scopes == ["product"]
    assert actor.facility_ids == []
    assert actor.id == str(admin_id)


@pytest.mark.asyncio
async def test_inactive_admin_rejected():
    admin = SimpleNamespace(id=uuid4(), is_active=False)
    session = _session_returning(admin)

    with pytest.raises(HTTPException) as exc:
        await get_support_agent_actor(
            request=MagicMock(),
            token_data=(str(admin.id), ProfileTypeEnum.ADMIN.value),
            session=session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_admin_rejected():
    session = _session_returning(None)

    with pytest.raises(HTTPException) as exc:
        await get_support_agent_actor(
            request=MagicMock(),
            token_data=(str(uuid4()), ProfileTypeEnum.ADMIN.value),
            session=session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_support_staff_care_provider_gets_facility_scope():
    facility_id = uuid4()
    cp_id = uuid4()
    cp = SimpleNamespace(
        care_provider_id=cp_id,
        role="support_staff",
        health_facility_id=facility_id,
    )
    session = _session_returning(cp)

    actor = await get_support_agent_actor(
        request=MagicMock(),
        token_data=(str(cp_id), ProfileTypeEnum.CARE_PROVIDER.value),
        session=session,
    )

    assert actor.role == ProfileTypeEnum.CARE_PROVIDER
    assert actor.allowed_scopes == ["facility"]
    assert actor.facility_ids == [str(facility_id)]


@pytest.mark.asyncio
async def test_support_staff_role_compared_case_insensitively():
    cp = SimpleNamespace(
        care_provider_id=uuid4(),
        role="Support_Staff",  # mixed case in PG
        health_facility_id=uuid4(),
    )
    session = _session_returning(cp)

    actor = await get_support_agent_actor(
        request=MagicMock(),
        token_data=(str(cp.care_provider_id), ProfileTypeEnum.CARE_PROVIDER.value),
        session=session,
    )
    assert actor.allowed_scopes == ["facility"]


@pytest.mark.asyncio
async def test_non_support_care_provider_rejected():
    cp = SimpleNamespace(
        care_provider_id=uuid4(),
        role="doctor",  # not support_staff
        health_facility_id=uuid4(),
    )
    session = _session_returning(cp)

    with pytest.raises(HTTPException) as exc:
        await get_support_agent_actor(
            request=MagicMock(),
            token_data=(str(cp.care_provider_id), ProfileTypeEnum.CARE_PROVIDER.value),
            session=session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_support_staff_without_facility_rejected():
    cp = SimpleNamespace(
        care_provider_id=uuid4(),
        role="support_staff",
        health_facility_id=None,
    )
    session = _session_returning(cp)

    with pytest.raises(HTTPException) as exc:
        await get_support_agent_actor(
            request=MagicMock(),
            token_data=(str(cp.care_provider_id), ProfileTypeEnum.CARE_PROVIDER.value),
            session=session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_care_provider_rejected():
    session = _session_returning(None)

    with pytest.raises(HTTPException) as exc:
        await get_support_agent_actor(
            request=MagicMock(),
            token_data=(str(uuid4()), ProfileTypeEnum.CARE_PROVIDER.value),
            session=session,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_patient_role_rejected():
    session = _session_returning(MagicMock())

    with pytest.raises(HTTPException) as exc:
        await get_support_agent_actor(
            request=MagicMock(),
            token_data=(str(uuid4()), ProfileTypeEnum.PATIENT.value),
            session=session,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_invalid_role_value_rejected():
    session = _session_returning(MagicMock())

    with pytest.raises(HTTPException) as exc:
        await get_support_agent_actor(
            request=MagicMock(),
            token_data=(str(uuid4()), "not-a-role"),
            session=session,
        )
    assert exc.value.status_code == 403
