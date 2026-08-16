"""Gamification REST API.

URL layout (one source of truth):

- /gamification/patients/{patient_id}/...            ← patient-scoped reads/writes
- /gamification/groups[/{group_id}]/...              ← groups as first-class resources
- /gamification/challenges[/{challenge_id}]/...      ← challenges as first-class resources
- /gamification/feed/{feed_event_id}/cheer           ← feed actions
- /gamification/care-providers/{cp_id}/...           ← CP dashboards & CP-owned reads
- /gamification/catalog/...                          ← global catalogs (achievements)
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_buddy_service,
    get_care_provider_access_service,
    get_challenge_service,
    get_cp_gamification_service,
    get_feed_service,
    get_gamification_service,
    get_group_service,
    get_leaderboard_service,
)
from lib.models.care_provider import CareProvider
from lib.schemas.gamification import (
    AchievementResponse,
    AddGroupMembersInput,
    BuddyDetailResponse,
    BuddyProgressResponse,
    BuddyRequestByCodeInput,
    BuddyRequestInput,
    BuddyResponse,
    ChallengeCreateInput,
    ChallengeDetailResponse,
    ChallengeParticipantResponse,
    ChallengeResponse,
    CheerInput,
    CPGamificationOverview,
    CPLeaderboardResponse,
    LeaderboardMetric,
    DailyHistoryResponse,
    DailyProgressResponse,
    FeedEventResponse,
    GroupCreateInput,
    GroupInfoResponse,
    GroupMemberResponse,
    GroupResponse,
    JoinByCodeInput,
    LeaderboardResponse,
    PatientEngagementSummary,
    PlayerProfileResponse,
    PlayerProfileUpdate,
    TaskCompletionResponse,
    WeeklyQuestResponse,
    XPHistoryResponse,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.gamification.achievement_catalog import ACHIEVEMENT_CATALOG
from lib.services.gamification.buddy_service import BuddyService
from lib.services.gamification.care_provider_service import CPGamificationService
from lib.services.gamification.challenge_service import ChallengeService
from lib.services.gamification.feed_service import FeedService
from lib.services.gamification.group_service import GroupService
from lib.services.gamification.leaderboard_service import LeaderboardService
from lib.services.gamification.service import GamificationService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse


router = APIRouter(prefix="/gamification", tags=["Gamification"])


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

# Caps applied to patient-created challenges (CPs and admins are uncapped)
MAX_PATIENT_CHALLENGE_XP = 200
MAX_PATIENT_CHALLENGE_BONUS = 100
MAX_PATIENT_CHALLENGE_DAYS = 30

_ALLOWED_BOARD_TYPES = {
    "weekly_xp",
    "monthly_xp",
    "weekly_steps",
    "streak",
    "challenge",
}


# ═══════════════════════════════════════════════════════════════════════════
# Auth helpers
# ═══════════════════════════════════════════════════════════════════════════


def _actor_read():
    return get_current_actor(
        allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
        care_provider_feature=CareProviderFeature.PATIENTS,
        care_provider_action=CareProviderPermissionAction.READ,
    )


def _actor_write():
    return get_current_actor(
        allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
        care_provider_feature=CareProviderFeature.PATIENTS,
        care_provider_action=CareProviderPermissionAction.CREATE,
    )


def _actor_any_role():
    """Any authenticated profile (patient, CP, or admin)."""
    return get_current_actor(
        allowed_roles=[
            ProfileTypeEnum.PATIENT,
            ProfileTypeEnum.CARE_PROVIDER,
            ProfileTypeEnum.ADMIN,
        ],
        check_permissions=False,
    )


def _cp_read():
    return get_current_care_provider(
        action=CareProviderPermissionAction.READ,
        feature=CareProviderFeature.PATIENTS,
        check_permissions=True,
    )


def _cp_write():
    return get_current_care_provider(
        action=CareProviderPermissionAction.CREATE,
        feature=CareProviderFeature.PATIENTS,
        check_permissions=True,
    )


def _cp_update():
    return get_current_care_provider(
        action=CareProviderPermissionAction.UPDATE,
        feature=CareProviderFeature.PATIENTS,
        check_permissions=True,
    )


async def _resolve_patient(
    patient_id: UUID,
    actor: Actor,
    cp_access: CareProviderAccessService,
) -> UUID:
    return await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=cp_access,
    )


async def _resolve_task_date(
    patient_id: UUID,
    task_date: Optional[str],
    service: GamificationService,
) -> date:
    if task_date:
        try:
            return date.fromisoformat(task_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use YYYY-MM-DD.",
            ) from exc
    return await service.get_patient_local_date(patient_id)


def _check_cp(cp_id: UUID, current_cp: CareProvider) -> None:
    if cp_id != current_cp.care_provider_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )


async def _ensure_group_member(
    group_service: GroupService, group_id: UUID, patient_id: UUID
) -> None:
    patient_groups = await group_service.get_patient_groups(patient_id)
    if not any(g.group_id == str(group_id) for g in patient_groups):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this group",
        )


async def _ensure_group_owner(
    group_service: GroupService,
    group_id: UUID,
    actor: Actor,
) -> None:
    """Group writes are restricted to the CP creator (CP-owned groups) or any active group admin."""
    from lib.models.gamification import Group, GroupMember
    from sqlalchemy import select as sa_select

    async with group_service.postgres_store.get_session() as session:
        group = await session.execute(
            sa_select(Group).where(Group.group_id == group_id)
        )
        group_row = group.scalars().first()
        if not group_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
            )

        # CP creator always wins
        if (
            group_row.created_by_type == "care_provider"
            and actor.role == ProfileTypeEnum.CARE_PROVIDER
            and str(group_row.created_by_id) == actor.id
        ):
            return

        # Patient admin within the group
        if actor.role == ProfileTypeEnum.PATIENT:
            member = await session.execute(
                sa_select(GroupMember).where(
                    GroupMember.group_id == group_id,
                    GroupMember.patient_id == UUID(actor.id),
                    GroupMember.is_active == True,  # noqa: E712
                )
            )
            row = member.scalars().first()
            if row and (row.role or "member") == "admin":
                return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the group owner can modify this group",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Patient-scoped: Profile / Streak
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/profile",
    response_model=SuccessResponse[PlayerProfileResponse],
)
async def get_profile(
    patient_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    profile = await service.get_or_create_profile(pid)
    return SuccessResponse(message="Profile retrieved", data=profile)


@router.patch(
    "/patients/{patient_id}/profile",
    response_model=SuccessResponse,
)
async def update_profile(
    patient_id: UUID,
    body: PlayerProfileUpdate,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(_actor_write()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    await service.update_profile(
        pid,
        visibility=body.leaderboard_visibility.value if body.leaderboard_visibility else None,
        title_slug=body.title_slug,
    )
    return SuccessResponse(message="Profile updated")


@router.post(
    "/patients/{patient_id}/streak/freeze",
    response_model=SuccessResponse[PlayerProfileResponse],
)
async def use_streak_freeze(
    patient_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(_actor_write()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        profile = await service.use_streak_freeze(pid)
        return SuccessResponse(message="Streak freeze applied", data=profile)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Patient-scoped: Daily Tasks
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/daily",
    response_model=SuccessResponse[DailyProgressResponse],
)
async def get_daily_progress(
    patient_id: UUID,
    task_date: Optional[str] = Query(None),
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    d = await _resolve_task_date(pid, task_date, service)
    progress = await service.get_daily_progress(pid, d)
    return SuccessResponse(message="Daily progress", data=progress)


@router.get(
    "/patients/{patient_id}/daily/history",
    response_model=SuccessResponse[DailyHistoryResponse],
)
async def get_daily_history(
    patient_id: UUID,
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        sd = date.fromisoformat(start_date)
        ed = date.fromisoformat(end_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Use YYYY-MM-DD.",
        ) from exc
    if (ed - sd).days > 31:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Date range cannot exceed 31 days.",
        )
    history = await service.get_daily_history(pid, sd, ed)
    return SuccessResponse(message="Daily history", data=history)


@router.post(
    "/patients/{patient_id}/tasks/{task_id}/complete",
    response_model=SuccessResponse[TaskCompletionResponse],
)
async def complete_task(
    patient_id: UUID,
    task_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(_actor_write()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        result = await service.complete_task(pid, task_id)
        return SuccessResponse(message="Task completed", data=result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Patient-scoped: Achievements / Quests / XP History
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/achievements",
    response_model=SuccessResponse[List[AchievementResponse]],
)
async def get_achievements(
    patient_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    achievements = await service.get_achievements(pid)
    return SuccessResponse(message="Achievements", data=achievements)


@router.get(
    "/patients/{patient_id}/achievements/recent",
    response_model=SuccessResponse[List[AchievementResponse]],
)
async def get_recent_achievements(
    patient_id: UUID,
    limit: int = Query(10, ge=1, le=50),
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    achievements = await service.get_recent_achievements(pid, limit=limit)
    return SuccessResponse(message="Recent achievements", data=achievements)


@router.get(
    "/patients/{patient_id}/quests/current",
    response_model=SuccessResponse[Optional[WeeklyQuestResponse]],
)
async def get_current_quest(
    patient_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    quest = await service.get_current_quest(pid)
    return SuccessResponse(message="Current quest", data=quest)


@router.get(
    "/patients/{patient_id}/history",
    response_model=SuccessResponse[XPHistoryResponse],
)
async def get_xp_history(
    patient_id: UUID,
    period: str = Query("week", pattern="^(week|month)$"),
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    history = await service.get_xp_history(pid, period)
    return SuccessResponse(message="XP history", data=history)


# ═══════════════════════════════════════════════════════════════════════════
# Patient-scoped: Buddies
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/buddies",
    response_model=SuccessResponse[List[BuddyResponse]],
)
async def get_buddies(
    patient_id: UUID,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    buddies = await service.get_buddies(pid)
    return SuccessResponse(message="Buddies", data=buddies)


@router.get(
    "/patients/{patient_id}/buddies/search",
    response_model=SuccessResponse[List[Dict[str, Any]]],
    summary="Search patients in the same facility for buddy requests",
)
async def search_patients_for_buddy(
    patient_id: UUID,
    q: str = Query(..., min_length=1, max_length=100, description="Name to search"),
    limit: int = Query(10, ge=1, le=20),
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)

    from sqlalchemy import func as sa_func
    from sqlalchemy import or_ as sa_or
    from sqlalchemy import select as sa_select

    from lib.models.gamification import Buddy
    from lib.models.patient import Patient

    async with service.postgres_store.get_session() as session:
        facility_result = await session.execute(
            sa_select(Patient.health_facility_id).where(Patient.patient_id == pid)
        )
        facility_id = facility_result.scalar()
        if not facility_id:
            return SuccessResponse(message="No facility", data=[])

        buddy_result = await session.execute(
            sa_select(Buddy.requester_id, Buddy.accepter_id, Buddy.status).where(
                sa_or(Buddy.requester_id == pid, Buddy.accepter_id == pid),
                Buddy.status.in_(["pending", "active"]),
            )
        )
        buddy_status_map: dict = {}
        for row in buddy_result.all():
            other_id = row.accepter_id if row.requester_id == pid else row.requester_id
            direction = None
            if row.status == "pending":
                direction = "outgoing" if row.requester_id == pid else "incoming"
            buddy_status_map[other_id] = {"status": row.status, "direction": direction}

        search_term = f"%{q.strip().lower()}%"
        result = await session.execute(
            sa_select(Patient.patient_id, Patient.first_name, Patient.last_name)
            .where(
                Patient.health_facility_id == facility_id,
                Patient.patient_id != pid,
                sa_func.lower(
                    sa_func.concat(
                        sa_func.coalesce(Patient.first_name, ""),
                        " ",
                        sa_func.coalesce(Patient.last_name, ""),
                    )
                ).like(search_term),
            )
            .limit(limit)
        )
        patients: List[Dict[str, Any]] = []
        for row in result.all():
            entry: Dict[str, Any] = {
                "patient_id": str(row.patient_id),
                "first_name": row.first_name,
                "last_name": row.last_name,
                "buddy_status": None,
                "buddy_direction": None,
            }
            existing = buddy_status_map.get(row.patient_id)
            if existing:
                entry["buddy_status"] = existing["status"]
                entry["buddy_direction"] = existing["direction"]
            patients.append(entry)

    return SuccessResponse(message="Search results", data=patients)


@router.post(
    "/patients/{patient_id}/buddies/request",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_buddy_request(
    patient_id: UUID,
    body: BuddyRequestInput,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(_actor_write()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.send_request(pid, body.accepter_id)
        return SuccessResponse(message="Buddy request sent")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/patients/{patient_id}/buddies/request-by-code",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_buddy_request_by_code(
    patient_id: UUID,
    body: BuddyRequestByCodeInput,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(_actor_write()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.send_request_by_code(pid, body.buddy_code)
        return SuccessResponse(message="Buddy request sent")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/patients/{patient_id}/buddies/{buddy_id}/accept",
    response_model=SuccessResponse,
)
async def accept_buddy_request(
    patient_id: UUID,
    buddy_id: UUID,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(_actor_write()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.accept_request(buddy_id, pid)
        return SuccessResponse(message="Buddy request accepted")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/patients/{patient_id}/buddies/{buddy_id}/reject",
    response_model=SuccessResponse,
)
async def reject_buddy_request(
    patient_id: UUID,
    buddy_id: UUID,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(_actor_write()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.reject_request(buddy_id, pid)
        return SuccessResponse(message="Buddy request rejected")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/patients/{patient_id}/buddies/{buddy_id}",
    response_model=SuccessResponse,
)
async def remove_buddy(
    patient_id: UUID,
    buddy_id: UUID,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(_actor_write()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.remove_buddy(buddy_id, pid)
        return SuccessResponse(message="Buddy removed")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/patients/{patient_id}/buddies/{buddy_id}/progress",
    response_model=SuccessResponse[BuddyProgressResponse],
)
async def get_buddy_progress(
    patient_id: UUID,
    buddy_id: UUID,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        progress = await service.get_buddy_progress(buddy_id, pid)
        return SuccessResponse(message="Buddy progress", data=progress)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/patients/{patient_id}/buddies/by-code/{buddy_code}",
    response_model=SuccessResponse[BuddyDetailResponse],
)
async def get_buddy_detail(
    patient_id: UUID,
    buddy_code: str,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    """Rich buddy details by buddy_code — name, picture, level, streaks, achievements."""
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        detail = await service.get_buddy_detail(buddy_code, pid)
        return SuccessResponse(message="Buddy detail", data=detail)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Patient-scoped: My Groups / My Challenges / My Feed / My Leaderboard
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/groups",
    response_model=SuccessResponse[List[GroupResponse]],
)
async def get_patient_groups(
    patient_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    groups = await service.get_patient_groups(pid)
    return SuccessResponse(message="Patient groups", data=groups)


@router.get(
    "/patients/{patient_id}/challenges/available",
    response_model=SuccessResponse[List[ChallengeResponse]],
)
async def get_available_challenges(
    patient_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    challenges = await service.get_available_challenges(pid)
    return SuccessResponse(message="Available challenges", data=challenges)


@router.get(
    "/patients/{patient_id}/challenges/active",
    response_model=SuccessResponse[List[ChallengeResponse]],
)
async def get_active_challenges(
    patient_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    challenges = await service.get_active_challenges(pid)
    return SuccessResponse(message="Active challenges", data=challenges)


@router.get(
    "/patients/{patient_id}/feed",
    response_model=SuccessResponse[List[FeedEventResponse]],
)
async def get_buddy_feed(
    patient_id: UUID,
    service: FeedService = Depends(get_feed_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    feed = await service.get_buddy_feed(pid)
    return SuccessResponse(message="Buddy feed", data=feed)


@router.get(
    "/patients/{patient_id}/leaderboards/{board_type}",
    response_model=SuccessResponse[LeaderboardResponse],
)
async def get_leaderboard(
    patient_id: UUID,
    board_type: str,
    scope: str = Query("global"),
    scope_id: Optional[UUID] = Query(None),
    service: LeaderboardService = Depends(get_leaderboard_service),
    group_service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_read()),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)

    if board_type not in _ALLOWED_BOARD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid board_type. Allowed: {', '.join(sorted(_ALLOWED_BOARD_TYPES))}",
        )

    if scope == "group" and scope_id:
        await _ensure_group_member(group_service, scope_id, pid)
    elif scope == "facility" and scope_id:
        from sqlalchemy import select as sa_select

        from lib.models.patient import Patient

        gam_service: GamificationService = get_gamification_service()
        async with gam_service.postgres_store.get_session() as session:
            result = await session.execute(
                sa_select(Patient.health_facility_id).where(Patient.patient_id == pid)
            )
            patient_facility = result.scalar()
        if patient_facility is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Patient is not associated with any facility",
            )
        if str(patient_facility) != str(scope_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this facility",
            )

    board = await service.get_leaderboard(board_type, scope, pid, scope_id=scope_id)
    return SuccessResponse(message="Leaderboard", data=board)


# ═══════════════════════════════════════════════════════════════════════════
# Groups (resource-addressed)
# ═══════════════════════════════════════════════════════════════════════════


class GroupUpdateInput(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    max_members: Optional[int] = Field(None, ge=2, le=200)


@router.post(
    "/groups",
    response_model=SuccessResponse[GroupResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_group(
    body: GroupCreateInput,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_write()),
):
    """Create a group. Patient creators become admin; CP creators own the group."""
    if body.group_type.value in ("care_provider", "facility") and actor.role != ProfileTypeEnum.CARE_PROVIDER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Only care providers can create {body.group_type.value} groups",
        )
    created_by_type = actor.role.value
    group = await service.create_group(
        name=body.name,
        group_type=body.group_type.value,
        created_by_id=UUID(actor.id),
        created_by_type=created_by_type,
        description=body.description,
        facility_id=body.facility_id,
        max_members=body.max_members,
    )
    resp = await service.get_group(group.group_id)
    return SuccessResponse(message="Group created", data=resp)


@router.get(
    "/groups/by-code/{invite_code}",
    response_model=SuccessResponse[GroupInfoResponse],
)
async def get_group_info(
    invite_code: str,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_read()),
):
    """Look up a group by invite code for the join-preview screen.

    Patient-only: the service performs a facility check against the caller's facility
    and renders 'your_role' relative to the caller.
    """
    if actor.role != ProfileTypeEnum.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can look up groups by invite code",
        )
    info = await service.get_group_info(invite_code, UUID(actor.id))
    if not info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )
    return SuccessResponse(message="Group info", data=info)


@router.get(
    "/groups/{group_id}",
    response_model=SuccessResponse[GroupResponse],
)
async def get_group(
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_read()),
):
    group = await service.get_group(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )
    # Access: patient must be a member; CP must be the creator
    if actor.role == ProfileTypeEnum.PATIENT:
        await _ensure_group_member(service, group_id, UUID(actor.id))
    elif actor.role == ProfileTypeEnum.CARE_PROVIDER:
        if not (group.created_by_type == "care_provider" and group.created_by_id == actor.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not the owner of this group",
            )
    return SuccessResponse(message="Group details", data=group)


@router.patch(
    "/groups/{group_id}",
    response_model=SuccessResponse[GroupResponse],
)
async def update_group(
    group_id: UUID,
    body: GroupUpdateInput,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_write()),
):
    await _ensure_group_owner(service, group_id, actor)
    try:
        updated = await service.update_group(
            group_id,
            name=body.name,
            description=body.description,
            max_members=body.max_members,
        )
        return SuccessResponse(message="Group updated", data=updated)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/groups/{group_id}",
    response_model=SuccessResponse,
)
async def delete_group(
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_write()),
):
    await _ensure_group_owner(service, group_id, actor)
    try:
        await service.delete_group(group_id)
        return SuccessResponse(message="Group deleted")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/groups/{group_id}/invite-code/rotate",
    response_model=SuccessResponse[Dict[str, str]],
)
async def rotate_group_invite_code(
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_write()),
):
    await _ensure_group_owner(service, group_id, actor)
    try:
        new_code = await service.rotate_invite_code(group_id)
        return SuccessResponse(
            message="Invite code rotated", data={"invite_code": new_code}
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/groups/{group_id}/join",
    response_model=SuccessResponse,
)
async def join_group(
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_write()),
):
    if actor.role != ProfileTypeEnum.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can join groups",
        )
    try:
        await service.join_group(group_id, UUID(actor.id))
        return SuccessResponse(message="Joined group")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/groups/join-by-code",
    response_model=SuccessResponse[GroupResponse],
)
async def join_group_by_code(
    body: JoinByCodeInput,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_write()),
):
    if actor.role != ProfileTypeEnum.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can join groups",
        )
    try:
        group = await service.join_by_code(body.invite_code, UUID(actor.id))
        return SuccessResponse(message="Joined group", data=group)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/groups/{group_id}/leave",
    response_model=SuccessResponse,
)
async def leave_group(
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_write()),
):
    if actor.role != ProfileTypeEnum.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can leave groups",
        )
    try:
        await service.leave_group(group_id, UUID(actor.id))
        return SuccessResponse(message="Left group")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/groups/{group_id}/members",
    response_model=SuccessResponse[List[GroupMemberResponse]],
)
async def get_group_members(
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_read()),
):
    if actor.role == ProfileTypeEnum.PATIENT:
        await _ensure_group_member(service, group_id, UUID(actor.id))
    elif actor.role == ProfileTypeEnum.CARE_PROVIDER:
        await _ensure_group_owner(service, group_id, actor)
    members = await service.get_members(group_id)
    return SuccessResponse(message="Group members", data=members)


@router.post(
    "/groups/{group_id}/members",
    response_model=SuccessResponse[Dict[str, int]],
    status_code=status.HTTP_201_CREATED,
)
async def add_group_members(
    group_id: UUID,
    body: AddGroupMembersInput,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_write()),
):
    """Bulk-add patients to a group. Group owner only (CP creator or patient admin)."""
    await _ensure_group_owner(service, group_id, actor)
    try:
        added = await service.add_members(group_id, body.patient_ids)
        return SuccessResponse(message=f"{added} member(s) added", data={"added": added})
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/groups/{group_id}/members/{patient_id}",
    response_model=SuccessResponse,
)
async def remove_group_member(
    group_id: UUID,
    patient_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_write()),
):
    await _ensure_group_owner(service, group_id, actor)
    try:
        await service.remove_member(group_id, patient_id)
        return SuccessResponse(message="Member removed")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/groups/{group_id}/leaderboard",
    response_model=SuccessResponse[LeaderboardResponse],
)
async def get_group_leaderboard(
    group_id: UUID,
    board_type: str = Query("weekly_xp"),
    service: LeaderboardService = Depends(get_leaderboard_service),
    group_service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_read()),
):
    if actor.role == ProfileTypeEnum.PATIENT:
        viewer_id = UUID(actor.id)
        await _ensure_group_member(group_service, group_id, viewer_id)
    else:
        # CP must own the group; CP is treated as an outside viewer for visibility purposes
        await _ensure_group_owner(group_service, group_id, actor)
        viewer_id = UUID(actor.id)

    board = await service.get_leaderboard(board_type, "group", viewer_id, scope_id=group_id)
    return SuccessResponse(message="Group leaderboard", data=board)


@router.get(
    "/groups/{group_id}/feed",
    response_model=SuccessResponse[List[FeedEventResponse]],
)
async def get_group_feed(
    group_id: UUID,
    service: FeedService = Depends(get_feed_service),
    group_service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(_actor_read()),
):
    if actor.role == ProfileTypeEnum.PATIENT:
        pid = UUID(actor.id)
    else:
        await _ensure_group_owner(group_service, group_id, actor)
        pid = UUID(actor.id)
    try:
        feed = await service.get_group_feed(group_id, pid)
        return SuccessResponse(message="Group feed", data=feed)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Challenges (resource-addressed)
# ═══════════════════════════════════════════════════════════════════════════


class ChallengeUpdateInput(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    target_value: Optional[float] = Field(None, gt=0)
    xp_reward: Optional[int] = Field(None, ge=1, le=10000)
    bonus_xp_winner: Optional[int] = Field(None, ge=0, le=5000)


@router.post(
    "/challenges",
    response_model=SuccessResponse[ChallengeResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_challenge(
    body: ChallengeCreateInput,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(_actor_write()),
):
    """Create a challenge. Caps are applied if the caller is a patient."""
    created_by_id = UUID(actor.id)
    created_by_type = actor.role.value
    is_patient = actor.role == ProfileTypeEnum.PATIENT

    challenge = await service.create_challenge(
        title=body.title,
        challenge_type=body.challenge_type.value,
        scope=body.scope.value,
        metric_type=body.metric_type.value,
        target_value=body.target_value,
        duration_days=min(body.duration_days, MAX_PATIENT_CHALLENGE_DAYS) if is_patient else body.duration_days,
        xp_reward=min(body.xp_reward, MAX_PATIENT_CHALLENGE_XP) if is_patient else body.xp_reward,
        created_by_id=created_by_id,
        created_by_type=created_by_type,
        description=body.description,
        bonus_xp_winner=min(body.bonus_xp_winner, MAX_PATIENT_CHALLENGE_BONUS) if is_patient else body.bonus_xp_winner,
        facility_id=None if is_patient else body.facility_id,
        is_opt_in=True if is_patient else body.is_opt_in,
        patient_ids=body.patient_ids,
        group_ids=body.group_ids,
    )
    detail = await service.get_challenge_detail(challenge.challenge_id, created_by_id)
    return SuccessResponse(message="Challenge created", data=detail.challenge)


@router.get(
    "/challenges/{challenge_id}",
    response_model=SuccessResponse[ChallengeDetailResponse],
)
async def get_challenge_detail(
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(_actor_read()),
):
    viewer_id = UUID(actor.id)
    try:
        detail = await service.get_challenge_detail(challenge_id, viewer_id)
        return SuccessResponse(message="Challenge details", data=detail)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch(
    "/challenges/{challenge_id}",
    response_model=SuccessResponse[ChallengeResponse],
)
async def update_challenge(
    challenge_id: UUID,
    body: ChallengeUpdateInput,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(_actor_write()),
):
    await _ensure_challenge_owner(service, challenge_id, actor)
    try:
        updated = await service.update_challenge(
            challenge_id,
            title=body.title,
            description=body.description,
            target_value=body.target_value,
            xp_reward=body.xp_reward,
            bonus_xp_winner=body.bonus_xp_winner,
        )
        return SuccessResponse(message="Challenge updated", data=updated)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/challenges/{challenge_id}",
    response_model=SuccessResponse,
)
async def cancel_challenge(
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(_actor_write()),
):
    await _ensure_challenge_owner(service, challenge_id, actor)
    try:
        await service.cancel_challenge(challenge_id)
        return SuccessResponse(message="Challenge cancelled")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/challenges/{challenge_id}/join",
    response_model=SuccessResponse,
)
async def join_challenge(
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(_actor_write()),
):
    if actor.role != ProfileTypeEnum.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can join challenges",
        )
    try:
        await service.join_challenge(challenge_id, UUID(actor.id))
        return SuccessResponse(message="Joined challenge")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/challenges/{challenge_id}/withdraw",
    response_model=SuccessResponse,
)
async def withdraw_challenge(
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(_actor_write()),
):
    if actor.role != ProfileTypeEnum.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can withdraw from challenges",
        )
    try:
        await service.withdraw_from_challenge(challenge_id, UUID(actor.id))
        return SuccessResponse(message="Withdrawn from challenge")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/challenges/{challenge_id}/leaderboard",
    response_model=SuccessResponse[List[ChallengeParticipantResponse]],
)
async def get_challenge_leaderboard(
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(_actor_read()),
):
    viewer_id = UUID(actor.id)
    try:
        leaderboard = await service.get_challenge_leaderboard(challenge_id, viewer_id)
        return SuccessResponse(message="Challenge leaderboard", data=leaderboard)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


async def _ensure_challenge_owner(
    service: ChallengeService, challenge_id: UUID, actor: Actor
) -> None:
    from sqlalchemy import select as sa_select

    from lib.models.gamification import Challenge

    async with service.postgres_store.get_session() as session:
        result = await session.execute(
            sa_select(Challenge).where(Challenge.challenge_id == challenge_id)
        )
        challenge = result.scalars().first()
    if not challenge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found"
        )
    if str(challenge.created_by_id) != actor.id or challenge.created_by_type != actor.role.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the creator can modify this challenge",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Feed (cheer)
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/feed/{feed_event_id}/cheer",
    response_model=SuccessResponse,
)
async def send_cheer(
    feed_event_id: UUID,
    body: CheerInput,
    service: FeedService = Depends(get_feed_service),
    actor: Actor = Depends(_actor_write()),
):
    if actor.role != ProfileTypeEnum.PATIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can send cheers",
        )
    try:
        result = await service.send_cheer(UUID(actor.id), feed_event_id, body.reaction.value)
        if result is None:
            return SuccessResponse(message="Cheer removed")
        return SuccessResponse(message="Cheer sent")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Care Provider scope
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/care-providers/{cp_id}/overview",
    response_model=SuccessResponse[CPGamificationOverview],
)
async def get_cp_overview(
    cp_id: UUID,
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(_cp_read()),
):
    _check_cp(cp_id, current_cp)
    overview = await service.get_overview(
        current_cp.care_provider_id,
        health_facility_id=current_cp.health_facility_id,
        is_admin=current_cp.is_admin,
    )
    return SuccessResponse(message="Gamification overview", data=overview)


@router.get(
    "/care-providers/{cp_id}/disengaged",
    response_model=SuccessResponse[List[PatientEngagementSummary]],
)
async def get_disengaged_patients(
    cp_id: UUID,
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(_cp_read()),
):
    _check_cp(cp_id, current_cp)
    patients = await service.get_disengaged_patients(
        current_cp.care_provider_id,
        health_facility_id=current_cp.health_facility_id,
        is_admin=current_cp.is_admin,
    )
    return SuccessResponse(message="Disengaged patients", data=patients)


@router.get(
    "/care-providers/{cp_id}/leaderboard",
    response_model=SuccessResponse[CPLeaderboardResponse],
)
async def get_cp_leaderboard(
    cp_id: UUID,
    metric: LeaderboardMetric = Query("streak"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=100),
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(_cp_read()),
):
    _check_cp(cp_id, current_cp)
    board = await service.get_leaderboard(
        current_cp.care_provider_id,
        metric=metric,
        limit=limit,
        offset=offset,
        search=search,
        health_facility_id=current_cp.health_facility_id,
        is_admin=current_cp.is_admin,
    )
    return SuccessResponse(message="Leaderboard", data=board)


@router.get(
    "/care-providers/{cp_id}/groups",
    response_model=SuccessResponse[List[GroupResponse]],
)
async def get_cp_groups(
    cp_id: UUID,
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(_cp_read()),
):
    _check_cp(cp_id, current_cp)
    groups = await service.get_groups(current_cp.care_provider_id)
    return SuccessResponse(message="Care provider groups", data=groups)


@router.get(
    "/care-providers/{cp_id}/challenges",
    response_model=SuccessResponse[List[ChallengeResponse]],
)
async def get_cp_challenges(
    cp_id: UUID,
    include_inactive: bool = Query(False),
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(_cp_read()),
):
    _check_cp(cp_id, current_cp)
    if not current_cp.health_facility_id:
        return SuccessResponse(message="Facility challenges", data=[])
    challenges = await service.get_facility_challenges(
        current_cp.health_facility_id, include_inactive=include_inactive
    )
    return SuccessResponse(message="Facility challenges", data=challenges)


@router.post(
    "/care-providers/{cp_id}/achievements/{achievement_id}/star",
    response_model=SuccessResponse,
)
async def star_achievement(
    cp_id: UUID,
    achievement_id: UUID,
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(_cp_update()),
):
    _check_cp(cp_id, current_cp)
    try:
        await service.star_achievement(current_cp.care_provider_id, achievement_id)
        return SuccessResponse(message="Achievement starred")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Catalog
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/catalog/achievements",
    response_model=SuccessResponse[List[Dict[str, Any]]],
)
async def list_achievements_catalog(
    include_hidden: bool = Query(False),
    actor: Actor = Depends(_actor_any_role()),
):
    """Static catalog of all defined achievements. Hidden ones omitted by default."""
    if include_hidden:
        return SuccessResponse(message="Achievements catalog", data=ACHIEVEMENT_CATALOG)
    visible = [a for a in ACHIEVEMENT_CATALOG if not a.get("is_hidden")]
    return SuccessResponse(message="Achievements catalog", data=visible)
