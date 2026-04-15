from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import load_module, make_module


def _fastapi_stub_module():
    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class APIRouter:
        def __init__(self, *args, **kwargs):
            self.routes = []

        def _decorator(self, path, **kwargs):
            def wrap(fn):
                self.routes.append(SimpleNamespace(path=path, endpoint=fn, kwargs=kwargs))
                return fn
            return wrap

        get = post = patch = delete = _decorator

    return make_module(
        "fastapi",
        APIRouter=APIRouter,
        Depends=lambda dep=None: dep,
        HTTPException=HTTPException,
        Query=lambda default=None, **kwargs: default,
        status=SimpleNamespace(
            HTTP_200_OK=200,
            HTTP_201_CREATED=201,
            HTTP_400_BAD_REQUEST=400,
            HTTP_403_FORBIDDEN=403,
            HTTP_404_NOT_FOUND=404,
        ),
    )


def _load_router(monkeypatch):
    profile_type = SimpleNamespace(PATIENT="PATIENT", CARE_PROVIDER="CARE_PROVIDER")

    class SuccessResponse:
        def __init__(self, **kw):
            self.__dict__.update(kw)

        def __class_getitem__(cls, _item):
            return cls

    def actor_dep_factory(**_kwargs):
        async def dependency():
            return None
        return dependency

    def cp_dep_factory(**_kwargs):
        async def dependency():
            return None
        return dependency

    extra_stubs = {
        "fastapi": _fastapi_stub_module(),
        "lib.core.constants": make_module(
            "lib.core.constants",
            ProfileTypeEnum=profile_type,
        ),
        "lib.dependencies.actor": make_module(
            "lib.dependencies.actor",
            Actor=object,
            get_current_actor=actor_dep_factory,
        ),
        "lib.dependencies.auth.care_provider_auth": make_module(
            "lib.dependencies.auth.care_provider_auth",
            get_current_care_provider=cp_dep_factory,
        ),
        "lib.dependencies.patient_access": make_module(
            "lib.dependencies.patient_access",
            resolve_patient_access=None,
        ),
        "lib.dependencies.service_dependencies": make_module(
            "lib.dependencies.service_dependencies",
            get_buddy_service=lambda: None,
            get_care_provider_access_service=lambda: None,
            get_challenge_service=lambda: None,
            get_cp_gamification_service=lambda: None,
            get_feed_service=lambda: None,
            get_gamification_service=lambda: None,
            get_group_service=lambda: None,
            get_leaderboard_service=lambda: None,
        ),
        "lib.models.care_provider": make_module(
            "lib.models.care_provider",
            CareProvider=type("CareProvider", (), {}),
        ),
        "lib.services.care_provider_access_service": make_module(
            "lib.services.care_provider_access_service",
            CareProviderAccessService=type("CareProviderAccessService", (), {}),
        ),
        "lib.services.gamification.buddy_service": make_module(
            "lib.services.gamification.buddy_service",
            BuddyService=type("BuddyService", (), {}),
        ),
        "lib.services.gamification.care_provider_service": make_module(
            "lib.services.gamification.care_provider_service",
            CPGamificationService=type("CPGamificationService", (), {}),
        ),
        "lib.services.gamification.challenge_service": make_module(
            "lib.services.gamification.challenge_service",
            ChallengeService=type("ChallengeService", (), {}),
        ),
        "lib.services.gamification.feed_service": make_module(
            "lib.services.gamification.feed_service",
            FeedService=type("FeedService", (), {}),
        ),
        "lib.services.gamification.group_service": make_module(
            "lib.services.gamification.group_service",
            GroupService=type("GroupService", (), {}),
        ),
        "lib.services.gamification.leaderboard_service": make_module(
            "lib.services.gamification.leaderboard_service",
            LeaderboardService=type("LeaderboardService", (), {}),
        ),
        "lib.services.gamification.service": make_module(
            "lib.services.gamification.service",
            GamificationService=type("GamificationService", (), {}),
        ),
        "lib.utils.care_provider_permissions": make_module(
            "lib.utils.care_provider_permissions",
            CareProviderFeature=SimpleNamespace(PATIENTS="patients"),
            CareProviderPermissionAction=SimpleNamespace(READ="read", CREATE="create", UPDATE="update"),
        ),
        "rest_server.response_models": make_module(
            "rest_server.response_models",
            SuccessResponse=SuccessResponse,
        ),
    }

    router_module = load_module(
        monkeypatch,
        "rest_server/v1/gamification/router.py",
        "gamification_test_router",
        extra_stubs,
    )

    async def resolve_patient_access(*, actor, patient_id, care_provider_access_service):
        if actor.role == profile_type.PATIENT:
            return actor.id
        assigned = await care_provider_access_service.is_patient_assigned(
            care_provider_id=actor.model.care_provider_id,
            patient_id=patient_id,
        )
        if not assigned:
            raise router_module.HTTPException(
                status_code=router_module.status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this patient",
            )
        return patient_id

    router_module.resolve_patient_access = resolve_patient_access
    return router_module


class TestGamificationRouter:
    @pytest.mark.asyncio
    async def test_resolve_task_date_rejects_invalid_format(self, monkeypatch):
        module = _load_router(monkeypatch)

        class FakeService:
            async def get_patient_local_date(self, _patient_id):
                raise AssertionError("should not be called")

        with pytest.raises(module.HTTPException) as exc:
            await module._resolve_task_date(uuid4(), "04-03-2026", FakeService())

        assert exc.value.status_code == 400
        assert "YYYY-MM-DD" in exc.value.detail

    @pytest.mark.asyncio
    async def test_canonical_update_profile_forwards_visibility_and_title(self, monkeypatch):
        module = _load_router(monkeypatch)
        service_calls = []
        patient_id = uuid4()

        class FakeService:
            async def update_profile(self, *args, **kwargs):
                service_calls.append((args, kwargs))

        body = SimpleNamespace(
            leaderboard_visibility=SimpleNamespace(value="public"),
            title_slug="champion",
        )
        actor = SimpleNamespace(id=patient_id, role="PATIENT", model=SimpleNamespace(patient_id=patient_id))

        response = await module.canonical_update_profile(
            patient_id=uuid4(),
            body=body,
            service=FakeService(),
            actor=actor,
            cp_access=SimpleNamespace(),
        )

        assert response.message == "Profile updated"
        assert service_calls == [((patient_id,), {"visibility": "public", "title_slug": "champion"})]

    @pytest.mark.asyncio
    async def test_canonical_get_group_members_requires_membership(self, monkeypatch):
        module = _load_router(monkeypatch)
        actor = SimpleNamespace(id=uuid4(), role="PATIENT", model=SimpleNamespace(patient_id=uuid4()))

        class FakeGroupService:
            async def get_patient_groups(self, _patient_id):
                return []

        # Stub _resolve_patient — production resolves patient_id via cp_access
        async def fake_resolve(_pid, _actor, _cp):
            return actor.model.patient_id
        monkeypatch.setattr(module, "_resolve_patient", fake_resolve)

        with pytest.raises(module.HTTPException) as exc:
            await module.canonical_get_group_members(
                patient_id=actor.model.patient_id,
                group_id=uuid4(),
                service=FakeGroupService(),
                actor=actor,
                cp_access=SimpleNamespace(),
            )

        assert exc.value.status_code == 403
        assert exc.value.detail == "Not a member of this group"

    @pytest.mark.asyncio
    async def test_canonical_join_challenge_maps_value_error_to_bad_request(self, monkeypatch):
        module = _load_router(monkeypatch)
        actor = SimpleNamespace(id=uuid4(), role="PATIENT", model=SimpleNamespace(patient_id=uuid4()))

        class FakeChallengeService:
            async def join_challenge(self, _challenge_id, _patient_id):
                raise ValueError("Challenge has ended")

        async def fake_resolve(_pid, _actor, _cp):
            return actor.model.patient_id
        monkeypatch.setattr(module, "_resolve_patient", fake_resolve)

        with pytest.raises(module.HTTPException) as exc:
            await module.canonical_join_challenge(
                patient_id=actor.model.patient_id,
                challenge_id=uuid4(),
                service=FakeChallengeService(),
                actor=actor,
                cp_access=SimpleNamespace(),
            )

        assert exc.value.status_code == 400
        assert exc.value.detail == "Challenge has ended"

    @pytest.mark.asyncio
    async def test_canonical_send_cheer_maps_value_error_to_bad_request(self, monkeypatch):
        module = _load_router(monkeypatch)
        actor = SimpleNamespace(id=uuid4(), role="PATIENT", model=SimpleNamespace(patient_id=uuid4()))

        class FakeFeedService:
            async def send_cheer(self, _patient_id, _feed_event_id, _reaction):
                # Production no longer raises this — kept for back-compat
                # of the bad-request mapping behavior
                raise ValueError("Cannot cheer your own event")

        async def fake_resolve(_pid, _actor, _cp):
            return actor.model.patient_id
        monkeypatch.setattr(module, "_resolve_patient", fake_resolve)

        with pytest.raises(module.HTTPException) as exc:
            await module.canonical_send_cheer(
                patient_id=actor.model.patient_id,
                feed_event_id=uuid4(),
                body=SimpleNamespace(reaction=SimpleNamespace(value="fire")),
                service=FakeFeedService(),
                actor=actor,
                cp_access=SimpleNamespace(),
            )

        assert exc.value.status_code == 400
        assert exc.value.detail == "Cannot cheer your own event"

    @pytest.mark.asyncio
    async def test_canonical_create_group_uses_actor_identity(self, monkeypatch):
        module = _load_router(monkeypatch)
        actor = SimpleNamespace(id=uuid4(), role="PATIENT")
        create_calls = []
        get_calls = []
        group_id = uuid4()

        class FakeGroupService:
            async def create_group(self, **kwargs):
                create_calls.append(kwargs)
                return SimpleNamespace(group_id=group_id)

            async def get_group(self, incoming_group_id):
                get_calls.append(incoming_group_id)
                return {"group_id": str(incoming_group_id)}

        # canonical_create_group now thunks to the legacy create_group
        # function which expects cp_access dependency.
        async def fake_resolve(_pid, _actor, _cp):
            return actor.id
        monkeypatch.setattr(module, "_resolve_patient", fake_resolve)

        response = await module.canonical_create_group(
            patient_id=actor.id,
            body=SimpleNamespace(
                name="Friends",
                group_type=SimpleNamespace(value="patient_created"),
                description="desc",
                facility_id=None,
                max_members=20,
            ),
            service=FakeGroupService(),
            actor=actor,
            cp_access=SimpleNamespace(),
        )

        assert response.message == "Group created"
        assert create_calls[0]["created_by_id"] == actor.id
        assert create_calls[0]["created_by_type"] == actor.role
        assert get_calls == [group_id]

    @pytest.mark.asyncio
    async def test_canonical_get_profile_resolves_provider_access(self, monkeypatch):
        module = _load_router(monkeypatch)
        patient_id = uuid4()
        cp_id = uuid4()
        actor = SimpleNamespace(
            id=cp_id,
            role="CARE_PROVIDER",
            model=SimpleNamespace(care_provider_id=cp_id),
        )
        service_calls = []

        class FakeService:
            async def get_or_create_profile(self, resolved_patient_id):
                service_calls.append(resolved_patient_id)
                return {"patient_id": str(resolved_patient_id)}

        class FakeAccess:
            async def is_patient_assigned(self, care_provider_id, patient_id):
                return care_provider_id == cp_id and patient_id == patient_id

        response = await module.canonical_get_profile(
            patient_id=patient_id,
            service=FakeService(),
            actor=actor,
            cp_access=FakeAccess(),
        )

        assert response.message == "Profile retrieved"
        assert service_calls == [patient_id]

    @pytest.mark.asyncio
    async def test_canonical_create_cp_challenge_rejects_mismatched_cp_id(self, monkeypatch):
        module = _load_router(monkeypatch)
        current_cp = SimpleNamespace(care_provider_id=uuid4())

        with pytest.raises(module.HTTPException) as exc:
            await module.canonical_create_cp_challenge(
                cp_id=uuid4(),
                body=SimpleNamespace(
                    title="April Sprint",
                    challenge_type=SimpleNamespace(value="weekly"),
                    scope=SimpleNamespace(value="individual"),
                    metric_type=SimpleNamespace(value="steps"),
                    target_value=10000,
                    duration_days=7,
                    xp_reward=100,
                    description=None,
                    bonus_xp_winner=0,
                    facility_id=None,
                    is_opt_in=False,
                    patient_ids=None,
                    group_ids=None,
                ),
                challenge_service=SimpleNamespace(),
                current_cp=current_cp,
            )

        assert exc.value.status_code == 403
        assert exc.value.detail == "Access denied"
