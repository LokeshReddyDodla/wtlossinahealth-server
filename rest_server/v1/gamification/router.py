"""Gamification REST API — profile, tasks, achievements, buddies, groups, challenges, leaderboards, feed, care provider."""

from datetime import date
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

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
    AddGroupMembersInput,
    AchievementResponse,
    ChallengeParticipantResponse,
    BuddyDetailResponse,
    BuddyProgressResponse,
    BuddyRequestByCodeInput,
    BuddyRequestInput,
    BuddyResponse,
    CPGamificationOverview,
    ChallengeCreateInput,
    ChallengeDetailResponse,
    ChallengeResponse,
    CheerInput,
    DailyProgressResponse,
    FeedEventResponse,
    GroupCreateInput,
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
canonical_router = APIRouter(tags=["Gamification"])

_PATIENT_ACTOR = dict(
    allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
    care_provider_feature=CareProviderFeature.PATIENTS,
    care_provider_action=CareProviderPermissionAction.READ,
)

_PATIENT_WRITE_ACTOR = dict(
    allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
    care_provider_feature=CareProviderFeature.PATIENTS,
    care_provider_action=CareProviderPermissionAction.CREATE,
)


async def _resolve_patient(
    patient_id: UUID,
    actor: Actor,
    care_provider_access_service: CareProviderAccessService,
) -> UUID:
    return await resolve_patient_access(
        actor=actor,
        patient_id=patient_id,
        care_provider_access_service=care_provider_access_service,
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


# ═══════════════════════════════════════════════════════════════════════════
# Player Profile
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/profile",
    response_model=SuccessResponse[PlayerProfileResponse],
)
async def get_profile(
    patient_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
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
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
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
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        profile = await service.use_streak_freeze(pid)
        return SuccessResponse(message="Streak freeze applied", data=profile)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Daily Tasks
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/daily",
    response_model=SuccessResponse[DailyProgressResponse],
)
async def get_daily_progress(
    patient_id: UUID,
    task_date: Optional[str] = Query(None),
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    d = await _resolve_task_date(pid, task_date, service)
    progress = await service.get_daily_progress(pid, d)
    return SuccessResponse(message="Daily progress", data=progress)


@router.post(
    "/patients/{patient_id}/tasks/{task_id}/complete",
    response_model=SuccessResponse[TaskCompletionResponse],
)
async def complete_task(
    patient_id: UUID,
    task_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        result = await service.complete_task(pid, task_id)
        return SuccessResponse(message="Task completed", data=result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Achievements
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/achievements",
    response_model=SuccessResponse[List[AchievementResponse]],
)
async def get_achievements(
    patient_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
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
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    achievements = await service.get_recent_achievements(pid, limit=limit)
    return SuccessResponse(message="Recent achievements", data=achievements)


# ═══════════════════════════════════════════════════════════════════════════
# Weekly Quest
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/quests/current",
    response_model=SuccessResponse[Optional[WeeklyQuestResponse]],
)
async def get_current_quest(
    patient_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    quest = await service.get_current_quest(pid)
    return SuccessResponse(message="Current quest", data=quest)


# ═══════════════════════════════════════════════════════════════════════════
# XP History
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/history",
    response_model=SuccessResponse[XPHistoryResponse],
)
async def get_xp_history(
    patient_id: UUID,
    period: str = Query("week", regex="^(week|month)$"),
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    history = await service.get_xp_history(pid, period)
    return SuccessResponse(message="XP history", data=history)


# ═══════════════════════════════════════════════════════════════════════════
# Buddy Search + Buddies
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/buddies/search",
    response_model=SuccessResponse[List[Dict]],
    summary="Search patients in the same facility for buddy requests",
)
async def search_patients_for_buddy(
    patient_id: UUID,
    q: str = Query(..., min_length=1, max_length=100, description="Name to search"),
    limit: int = Query(10, ge=1, le=20),
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    """Search for patients by name within the same facility. Returns basic info only (id, name) for buddy request purposes."""
    pid = await _resolve_patient(patient_id, actor, cp_access)

    from sqlalchemy import select as sa_select, func as sa_func
    from lib.models.patient import Patient

    from sqlalchemy import or_ as sa_or
    from lib.models.gamification import Buddy

    async with service.postgres_store.get_session() as session:
        # Get the requesting patient's facility
        facility_result = await session.execute(
            sa_select(Patient.health_facility_id).where(Patient.patient_id == pid)
        )
        facility_id = facility_result.scalar()

        if not facility_id:
            return SuccessResponse(message="No facility", data=[])

        # Get existing buddy relationships (pending or active) for status display
        buddy_result = await session.execute(
            sa_select(Buddy.requester_id, Buddy.accepter_id, Buddy.status).where(
                sa_or(
                    Buddy.requester_id == pid,
                    Buddy.accepter_id == pid,
                ),
                Buddy.status.in_(["pending", "active"]),
            )
        )
        buddy_status_map: dict = {}  # other_patient_id -> {"status": ..., "direction": ...}
        for row in buddy_result.all():
            other_id = row.accepter_id if row.requester_id == pid else row.requester_id
            direction = None
            if row.status == "pending":
                direction = "outgoing" if row.requester_id == pid else "incoming"
            buddy_status_map[other_id] = {"status": row.status, "direction": direction}

        # Search by first_name or last_name (case-insensitive) within same facility
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
        patients = []
        for row in result.all():
            entry = {
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


@router.get(
    "/patients/{patient_id}/buddies",
    response_model=SuccessResponse[List[BuddyResponse]],
)
async def get_buddies(
    patient_id: UUID,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    buddies = await service.get_buddies(pid)
    return SuccessResponse(message="Buddies", data=buddies)


@router.post(
    "/patients/{patient_id}/buddies/request",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_buddy_request(
    patient_id: UUID,
    body: BuddyRequestInput,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
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
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
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
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
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
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
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
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
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
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        progress = await service.get_buddy_progress(buddy_id, pid)
        return SuccessResponse(message="Buddy progress", data=progress)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/patients/{patient_id}/buddies/{buddy_id}",
    response_model=SuccessResponse[BuddyDetailResponse],
)
async def get_buddy_detail(
    patient_id: UUID,
    buddy_id: UUID,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    """Rich buddy details — name, picture, level, streaks, achievements."""
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        detail = await service.get_buddy_detail(buddy_id, pid)
        return SuccessResponse(message="Buddy detail", data=detail)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Groups
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/patients/{patient_id}/groups",
    response_model=SuccessResponse[GroupResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_group(
    patient_id: UUID,
    body: GroupCreateInput,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    # Only care providers can create care_provider or facility groups
    if body.group_type.value in ("care_provider", "facility") and actor.role != "care_provider":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Only care providers can create {body.group_type.value} groups",
        )
    group = await service.create_group(
        name=body.name,
        group_type=body.group_type.value,
        created_by_id=pid,
        created_by_type=actor.role.value if hasattr(actor.role, "value") else str(actor.role),
        description=body.description,
        facility_id=body.facility_id,
        max_members=body.max_members,
    )
    resp = await service.get_group(group.group_id)
    return SuccessResponse(message="Group created", data=resp)


@router.get(
    "/patients/{patient_id}/groups/{group_id}",
    response_model=SuccessResponse[GroupResponse],
)
async def get_group(
    patient_id: UUID,
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    # Verify membership (or care provider who created it)
    patient_groups = await service.get_patient_groups(pid)
    if not any(g.group_id == str(group_id) for g in patient_groups):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group")
    group = await service.get_group(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return SuccessResponse(message="Group details", data=group)


@router.post("/patients/{patient_id}/groups/{group_id}/join", response_model=SuccessResponse)
async def join_group(
    patient_id: UUID,
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.join_group(group_id, pid)
        return SuccessResponse(message="Joined group")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/patients/{patient_id}/groups/join-by-code",
    response_model=SuccessResponse[GroupResponse],
)
async def join_group_by_code(
    patient_id: UUID,
    body: JoinByCodeInput,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    """Join a group using a shareable invite code (e.g. 'AHX392')."""
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        group = await service.join_by_code(body.invite_code, pid)
        return SuccessResponse(message="Joined group", data=group)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/patients/{patient_id}/groups/{group_id}/leave", response_model=SuccessResponse)
async def leave_group(
    patient_id: UUID,
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.leave_group(group_id, pid)
        return SuccessResponse(message="Left group")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/patients/{patient_id}/groups/{group_id}/members",
    response_model=SuccessResponse[List[GroupMemberResponse]],
)
async def get_group_members(
    patient_id: UUID,
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    # Verify the caller is a member of this group
    pid = await _resolve_patient(patient_id, actor, cp_access)
    patient_groups = await service.get_patient_groups(pid)
    if not any(g.group_id == str(group_id) for g in patient_groups):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group")
    members = await service.get_members(group_id)
    return SuccessResponse(message="Group members", data=members)


@router.get(
    "/patients/{patient_id}/groups/{group_id}/leaderboard",
    response_model=SuccessResponse[LeaderboardResponse],
)
async def get_group_leaderboard(
    patient_id: UUID,
    group_id: UUID,
    board_type: str = Query("weekly_xp"),
    service: LeaderboardService = Depends(get_leaderboard_service),
    group_service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    # Verify group membership
    patient_groups = await group_service.get_patient_groups(pid)
    if not any(g.group_id == str(group_id) for g in patient_groups):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group")
    board = await service.get_leaderboard(
        board_type, "group", pid, scope_id=group_id
    )
    return SuccessResponse(message="Group leaderboard", data=board)


@router.get(
    "/patients/{patient_id}/groups",
    response_model=SuccessResponse[List[GroupResponse]],
)
async def get_patient_groups(
    patient_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    groups = await service.get_patient_groups(pid)
    return SuccessResponse(message="Patient groups", data=groups)


# ═══════════════════════════════════════════════════════════════════════════
# Challenges
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/challenges/available",
    response_model=SuccessResponse[List[ChallengeResponse]],
)
async def get_available_challenges(
    patient_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
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
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    challenges = await service.get_active_challenges(pid)
    return SuccessResponse(message="Active challenges", data=challenges)


@router.post("/patients/{patient_id}/challenges/{challenge_id}/join", response_model=SuccessResponse)
async def join_challenge(
    patient_id: UUID,
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.join_challenge(challenge_id, pid)
        return SuccessResponse(message="Joined challenge")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/patients/{patient_id}/challenges/{challenge_id}/withdraw", response_model=SuccessResponse)
async def withdraw_challenge(
    patient_id: UUID,
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.withdraw_from_challenge(challenge_id, pid)
        return SuccessResponse(message="Withdrawn from challenge")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/patients/{patient_id}/challenges/{challenge_id}",
    response_model=SuccessResponse[ChallengeDetailResponse],
)
async def get_challenge_detail(
    patient_id: UUID,
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        detail = await service.get_challenge_detail(challenge_id, pid)
        return SuccessResponse(message="Challenge details", data=detail)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/patients/{patient_id}/challenges/{challenge_id}/leaderboard",
    response_model=SuccessResponse[List[ChallengeParticipantResponse]],
)
async def get_challenge_leaderboard(
    patient_id: UUID,
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        leaderboard = await service.get_challenge_leaderboard(challenge_id, pid)
        return SuccessResponse(message="Challenge leaderboard", data=leaderboard)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/challenges",
    response_model=SuccessResponse[ChallengeResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_challenge(
    body: ChallengeCreateInput,
    challenge_service: ChallengeService = Depends(get_challenge_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.CREATE,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    challenge = await challenge_service.create_challenge(
        title=body.title,
        challenge_type=body.challenge_type.value,
        scope=body.scope.value,
        metric_type=body.metric_type.value,
        target_value=body.target_value,
        duration_days=body.duration_days,
        xp_reward=body.xp_reward,
        created_by_id=current_cp.care_provider_id,
        created_by_type="care_provider",
        description=body.description,
        bonus_xp_winner=body.bonus_xp_winner,
        facility_id=body.facility_id,
        is_opt_in=body.is_opt_in,
        patient_ids=body.patient_ids,
        group_ids=body.group_ids,
    )
    detail = await challenge_service.get_challenge_detail(
        challenge.challenge_id,
        current_cp.care_provider_id,
    )
    return SuccessResponse(message="Challenge created", data=detail.challenge)


@router.post(
    "/patients/{patient_id}/challenges",
    response_model=SuccessResponse[ChallengeResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Patient-created challenge",
)
async def patient_create_challenge(
    patient_id: UUID,
    body: ChallengeCreateInput,
    challenge_service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    """Allow patients to create their own challenges (opt-in, capped XP)."""
    pid = await _resolve_patient(patient_id, actor, cp_access)
    # Patients can only create opt-in challenges with capped rewards
    MAX_PATIENT_XP = 200
    MAX_PATIENT_BONUS = 100
    challenge = await challenge_service.create_challenge(
        title=body.title,
        challenge_type=body.challenge_type.value,
        scope=body.scope.value,
        metric_type=body.metric_type.value,
        target_value=body.target_value,
        duration_days=min(body.duration_days, 30),  # Max 30 days for patient challenges
        xp_reward=min(body.xp_reward, MAX_PATIENT_XP),
        created_by_id=pid,
        created_by_type="patient",
        description=body.description,
        bonus_xp_winner=min(body.bonus_xp_winner, MAX_PATIENT_BONUS),
        is_opt_in=True,  # Always opt-in for patient-created
        patient_ids=body.patient_ids,
        group_ids=body.group_ids,
    )
    detail = await challenge_service.get_challenge_detail(challenge.challenge_id, pid)
    return SuccessResponse(message="Challenge created", data=detail.challenge)


# ═══════════════════════════════════════════════════════════════════════════
# Leaderboards
# ═══════════════════════════════════════════════════════════════════════════


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
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)

    # Validate board_type
    allowed_board_types = {"weekly_xp", "monthly_xp", "weekly_steps", "streak", "challenge"}
    if board_type not in allowed_board_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid board_type. Allowed: {', '.join(sorted(allowed_board_types))}",
        )

    # Validate scope access
    if scope == "group" and scope_id:
        _group_service = get_group_service()
        patient_groups = await _group_service.get_patient_groups(pid)
        if not any(g.group_id == str(scope_id) for g in patient_groups):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group")
    elif scope == "facility" and scope_id:
        _gam_service = get_gamification_service()
        async with _gam_service.postgres_store.get_session() as _session:
            from sqlalchemy import select as _select
            from lib.models.patient import Patient as _Patient
            _result = await _session.execute(
                _select(_Patient.health_facility_id).where(_Patient.patient_id == pid)
            )
            patient_facility = _result.scalar()
            if patient_facility is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Patient is not associated with any facility",
                )
            if str(patient_facility) != str(scope_id):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this facility")

    board = await service.get_leaderboard(board_type, scope, pid, scope_id=scope_id)
    return SuccessResponse(message="Leaderboard", data=board)


# ═══════════════════════════════════════════════════════════════════════════
# Activity Feed & Cheers
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/patients/{patient_id}/feed/buddies",
    response_model=SuccessResponse[List[FeedEventResponse]],
)
async def get_buddy_feed(
    patient_id: UUID,
    service: FeedService = Depends(get_feed_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    feed = await service.get_buddy_feed(pid)
    return SuccessResponse(message="Buddy feed", data=feed)


@router.get(
    "/patients/{patient_id}/groups/{group_id}/feed",
    response_model=SuccessResponse[List[FeedEventResponse]],
)
async def get_group_feed(
    patient_id: UUID,
    group_id: UUID,
    service: FeedService = Depends(get_feed_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        feed = await service.get_group_feed(group_id, pid)
        return SuccessResponse(message="Group feed", data=feed)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/patients/{patient_id}/feed/{feed_event_id}/cheer",
    response_model=SuccessResponse,
)
async def send_cheer(
    patient_id: UUID,
    feed_event_id: UUID,
    body: CheerInput,
    service: FeedService = Depends(get_feed_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        result = await service.send_cheer(pid, feed_event_id, body.reaction.value)
        if result is None:
            return SuccessResponse(message="Cheer removed")
        return SuccessResponse(message="Cheer sent")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Care Provider Endpoints
# ═══════════════════════════════════════════════════════════════════════════


@router.get(
    "/care-providers/{cp_id}/overview",
    response_model=SuccessResponse[CPGamificationOverview],
)
async def get_cp_overview(
    cp_id: UUID,
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    if cp_id != current_cp.care_provider_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    overview = await service.get_overview(current_cp.care_provider_id)
    return SuccessResponse(message="Gamification overview", data=overview)


@router.get(
    "/care-providers/{cp_id}/at-risk",
    response_model=SuccessResponse[List[PatientEngagementSummary]],
)
async def get_at_risk_patients(
    cp_id: UUID,
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    if cp_id != current_cp.care_provider_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    patients = await service.get_at_risk_patients(current_cp.care_provider_id)
    return SuccessResponse(message="At-risk patients", data=patients)


@router.post(
    "/care-providers/{cp_id}/challenges",
    response_model=SuccessResponse[ChallengeResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_cp_challenge(
    cp_id: UUID,
    body: ChallengeCreateInput,
    challenge_service: ChallengeService = Depends(get_challenge_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.CREATE,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    if cp_id != current_cp.care_provider_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    challenge = await challenge_service.create_challenge(
        title=body.title,
        challenge_type=body.challenge_type.value,
        scope=body.scope.value,
        metric_type=body.metric_type.value,
        target_value=body.target_value,
        duration_days=body.duration_days,
        xp_reward=body.xp_reward,
        created_by_id=current_cp.care_provider_id,
        created_by_type="care_provider",
        description=body.description,
        bonus_xp_winner=body.bonus_xp_winner,
        facility_id=body.facility_id,
        is_opt_in=body.is_opt_in,
        patient_ids=body.patient_ids,
        group_ids=body.group_ids,
    )
    detail = await challenge_service.get_challenge_detail(
        challenge.challenge_id, cp_id
    )
    return SuccessResponse(message="Challenge created", data=detail.challenge)


@router.post(
    "/care-providers/{cp_id}/groups/{group_id}/members",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_group_members(
    cp_id: UUID,
    group_id: UUID,
    body: AddGroupMembersInput,
    service: GroupService = Depends(get_group_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.CREATE,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    if cp_id != current_cp.care_provider_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    try:
        added = await service.add_members(group_id, body.patient_ids)
        return SuccessResponse(message=f"{added} member(s) added", data={"added": added})
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/care-providers/{cp_id}/achievements/{achievement_id}/star",
    response_model=SuccessResponse,
)
async def star_achievement(
    cp_id: UUID,
    achievement_id: UUID,
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.UPDATE,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    try:
        if cp_id != current_cp.care_provider_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        await service.star_achievement(current_cp.care_provider_id, achievement_id)
        return SuccessResponse(message="Achievement starred")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/care-providers/{cp_id}/groups",
    response_model=SuccessResponse[List[GroupResponse]],
)
async def get_cp_groups(
    cp_id: UUID,
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    if cp_id != current_cp.care_provider_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    groups = await service.get_groups(current_cp.care_provider_id)
    return SuccessResponse(message="Care provider groups", data=groups)


# ═══════════════════════════════════════════════════════════════════════════
# Canonical Contract Aliases
# ═══════════════════════════════════════════════════════════════════════════


@canonical_router.get(
    "/patients/{patient_id}/gamification/profile",
    response_model=SuccessResponse[PlayerProfileResponse],
)
async def canonical_get_profile(
    patient_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    profile = await service.get_or_create_profile(pid)
    return SuccessResponse(message="Profile retrieved", data=profile)


@canonical_router.patch(
    "/patients/{patient_id}/gamification/profile",
    response_model=SuccessResponse,
)
async def canonical_update_profile(
    patient_id: UUID,
    body: PlayerProfileUpdate,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    await service.update_profile(
        pid,
        visibility=body.leaderboard_visibility.value if body.leaderboard_visibility else None,
        title_slug=body.title_slug,
    )
    return SuccessResponse(message="Profile updated")


@canonical_router.post(
    "/patients/{patient_id}/gamification/streak/freeze",
    response_model=SuccessResponse[PlayerProfileResponse],
)
async def canonical_use_streak_freeze(
    patient_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    profile = await service.use_streak_freeze(pid)
    return SuccessResponse(message="Streak freeze applied", data=profile)


@canonical_router.get(
    "/patients/{patient_id}/gamification/daily",
    response_model=SuccessResponse[DailyProgressResponse],
)
async def canonical_get_daily_progress(
    patient_id: UUID,
    task_date: Optional[str] = Query(None),
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    d = await _resolve_task_date(pid, task_date, service)
    progress = await service.get_daily_progress(pid, d)
    return SuccessResponse(message="Daily progress", data=progress)


@canonical_router.post(
    "/patients/{patient_id}/gamification/tasks/{task_id}/complete",
    response_model=SuccessResponse[TaskCompletionResponse],
)
async def canonical_complete_task(
    patient_id: UUID,
    task_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    result = await service.complete_task(pid, task_id)
    return SuccessResponse(message="Task completed", data=result)


@canonical_router.get(
    "/patients/{patient_id}/gamification/quests/current",
    response_model=SuccessResponse[Optional[WeeklyQuestResponse]],
)
async def canonical_get_current_quest(
    patient_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    quest = await service.get_current_quest(pid)
    return SuccessResponse(message="Current quest", data=quest)


@canonical_router.get(
    "/patients/{patient_id}/gamification/achievements",
    response_model=SuccessResponse[List[AchievementResponse]],
)
async def canonical_get_achievements(
    patient_id: UUID,
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    achievements = await service.get_achievements(pid)
    return SuccessResponse(message="Achievements", data=achievements)


@canonical_router.get(
    "/patients/{patient_id}/gamification/achievements/recent",
    response_model=SuccessResponse[List[AchievementResponse]],
)
async def canonical_get_recent_achievements(
    patient_id: UUID,
    limit: int = Query(10, ge=1, le=50),
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    achievements = await service.get_recent_achievements(pid, limit=limit)
    return SuccessResponse(message="Recent achievements", data=achievements)


@canonical_router.get(
    "/patients/{patient_id}/gamification/buddies/search",
    response_model=SuccessResponse[List[Dict]],
    summary="Search patients in the same facility for buddy requests",
)
async def canonical_search_patients_for_buddy(
    patient_id: UUID,
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=20),
    service: GamificationService = Depends(get_gamification_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    return await search_patients_for_buddy(patient_id, q, limit, service, actor, cp_access)


@canonical_router.get(
    "/patients/{patient_id}/gamification/buddies",
    response_model=SuccessResponse[List[BuddyResponse]],
)
async def canonical_get_buddies(
    patient_id: UUID,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    buddies = await service.get_buddies(pid)
    return SuccessResponse(message="Buddies", data=buddies)


@canonical_router.post(
    "/patients/{patient_id}/gamification/buddies/request",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
)
async def canonical_send_buddy_request(
    patient_id: UUID,
    body: BuddyRequestInput,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    await service.send_request(pid, body.accepter_id)
    return SuccessResponse(message="Buddy request sent")


@canonical_router.post(
    "/patients/{patient_id}/gamification/buddies/{buddy_id}/accept",
    response_model=SuccessResponse,
)
async def canonical_accept_buddy_request(
    patient_id: UUID,
    buddy_id: UUID,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    await service.accept_request(buddy_id, pid)
    return SuccessResponse(message="Buddy request accepted")


@canonical_router.post(
    "/patients/{patient_id}/gamification/buddies/{buddy_id}/reject",
    response_model=SuccessResponse,
)
async def canonical_reject_buddy_request(
    patient_id: UUID,
    buddy_id: UUID,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    return await reject_buddy_request(patient_id, buddy_id, service, actor, cp_access)


@canonical_router.delete(
    "/patients/{patient_id}/gamification/buddies/{buddy_id}",
    response_model=SuccessResponse,
)
async def canonical_remove_buddy(
    patient_id: UUID,
    buddy_id: UUID,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    await service.remove_buddy(buddy_id, pid)
    return SuccessResponse(message="Buddy removed")


@canonical_router.get(
    "/patients/{patient_id}/gamification/buddies/{buddy_id}/progress",
    response_model=SuccessResponse[BuddyProgressResponse],
)
async def canonical_get_buddy_progress(
    patient_id: UUID,
    buddy_id: UUID,
    service: BuddyService = Depends(get_buddy_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    progress = await service.get_buddy_progress(buddy_id, pid)
    return SuccessResponse(message="Buddy progress", data=progress)


@canonical_router.get(
    "/patients/{patient_id}/gamification/groups",
    response_model=SuccessResponse[List[GroupResponse]],
)
async def canonical_get_patient_groups(
    patient_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    groups = await service.get_patient_groups(pid)
    return SuccessResponse(message="Patient groups", data=groups)


@canonical_router.post(
    "/patients/{patient_id}/gamification/groups",
    response_model=SuccessResponse[GroupResponse],
    status_code=status.HTTP_201_CREATED,
)
async def canonical_create_group(
    patient_id: UUID,
    body: GroupCreateInput,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    return await create_group(patient_id, body, service, actor, cp_access)


@canonical_router.get(
    "/patients/{patient_id}/gamification/groups/{group_id}",
    response_model=SuccessResponse[GroupResponse],
)
async def canonical_get_group(
    patient_id: UUID,
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    patient_groups = await service.get_patient_groups(pid)
    if not any(g.group_id == str(group_id) for g in patient_groups):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group")
    group = await service.get_group(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return SuccessResponse(message="Group details", data=group)


@canonical_router.post(
    "/patients/{patient_id}/gamification/groups/{group_id}/join",
    response_model=SuccessResponse,
)
async def canonical_join_group(
    patient_id: UUID,
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.join_group(group_id, pid)
        return SuccessResponse(message="Joined group")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@canonical_router.delete(
    "/patients/{patient_id}/gamification/groups/{group_id}/leave",
    response_model=SuccessResponse,
)
async def canonical_leave_group(
    patient_id: UUID,
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.leave_group(group_id, pid)
        return SuccessResponse(message="Left group")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@canonical_router.get(
    "/patients/{patient_id}/gamification/groups/{group_id}/members",
    response_model=SuccessResponse[List[GroupMemberResponse]],
)
async def canonical_get_group_members(
    patient_id: UUID,
    group_id: UUID,
    service: GroupService = Depends(get_group_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    patient_groups = await service.get_patient_groups(pid)
    if not any(g.group_id == str(group_id) for g in patient_groups):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this group")
    members = await service.get_members(group_id)
    return SuccessResponse(message="Group members", data=members)


@canonical_router.get(
    "/patients/{patient_id}/gamification/groups/{group_id}/leaderboard",
    response_model=SuccessResponse[LeaderboardResponse],
)
async def canonical_get_group_leaderboard(
    patient_id: UUID,
    group_id: UUID,
    board_type: str = Query("weekly_xp"),
    service: LeaderboardService = Depends(get_leaderboard_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    board = await service.get_leaderboard(
        board_type,
        "group",
        pid,
        scope_id=group_id,
    )
    return SuccessResponse(message="Group leaderboard", data=board)


@canonical_router.get(
    "/patients/{patient_id}/gamification/groups/{group_id}/feed",
    response_model=SuccessResponse[List[FeedEventResponse]],
)
async def canonical_get_group_feed(
    patient_id: UUID,
    group_id: UUID,
    service: FeedService = Depends(get_feed_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        feed = await service.get_group_feed(group_id, pid)
        return SuccessResponse(message="Group feed", data=feed)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@canonical_router.get(
    "/patients/{patient_id}/gamification/challenges/available",
    response_model=SuccessResponse[List[ChallengeResponse]],
)
async def canonical_get_available_challenges(
    patient_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    challenges = await service.get_available_challenges(pid)
    return SuccessResponse(message="Available challenges", data=challenges)


@canonical_router.get(
    "/patients/{patient_id}/gamification/challenges/active",
    response_model=SuccessResponse[List[ChallengeResponse]],
)
async def canonical_get_active_challenges(
    patient_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    challenges = await service.get_active_challenges(pid)
    return SuccessResponse(message="Active challenges", data=challenges)


@canonical_router.post(
    "/patients/{patient_id}/gamification/challenges/{challenge_id}/join",
    response_model=SuccessResponse,
)
async def canonical_join_challenge(
    patient_id: UUID,
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.join_challenge(challenge_id, pid)
        return SuccessResponse(message="Joined challenge")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@canonical_router.post(
    "/patients/{patient_id}/gamification/challenges/{challenge_id}/withdraw",
    response_model=SuccessResponse,
)
async def canonical_withdraw_challenge(
    patient_id: UUID,
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.withdraw_from_challenge(challenge_id, pid)
        return SuccessResponse(message="Withdrawn from challenge")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@canonical_router.get(
    "/patients/{patient_id}/gamification/challenges/{challenge_id}",
    response_model=SuccessResponse[ChallengeDetailResponse],
)
async def canonical_get_challenge_detail(
    patient_id: UUID,
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        detail = await service.get_challenge_detail(challenge_id, pid)
        return SuccessResponse(message="Challenge details", data=detail)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@canonical_router.get(
    "/patients/{patient_id}/gamification/challenges/{challenge_id}/leaderboard",
    response_model=SuccessResponse[List[ChallengeParticipantResponse]],
)
async def canonical_get_challenge_leaderboard(
    patient_id: UUID,
    challenge_id: UUID,
    service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        leaderboard = await service.get_challenge_leaderboard(challenge_id, pid)
        return SuccessResponse(message="Challenge leaderboard", data=leaderboard)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@canonical_router.post(
    "/patients/{patient_id}/gamification/challenges",
    response_model=SuccessResponse[ChallengeResponse],
    status_code=status.HTTP_201_CREATED,
)
async def canonical_patient_create_challenge(
    patient_id: UUID,
    body: ChallengeCreateInput,
    challenge_service: ChallengeService = Depends(get_challenge_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    return await patient_create_challenge(patient_id, body, challenge_service, actor, cp_access)


@canonical_router.post(
    "/gamification/challenges",
    response_model=SuccessResponse[ChallengeResponse],
    status_code=status.HTTP_201_CREATED,
)
async def canonical_create_challenge(
    body: ChallengeCreateInput,
    challenge_service: ChallengeService = Depends(get_challenge_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.CREATE,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    challenge = await challenge_service.create_challenge(
        title=body.title,
        challenge_type=body.challenge_type.value,
        scope=body.scope.value,
        metric_type=body.metric_type.value,
        target_value=body.target_value,
        duration_days=body.duration_days,
        xp_reward=body.xp_reward,
        created_by_id=current_cp.care_provider_id,
        created_by_type="care_provider",
        description=body.description,
        bonus_xp_winner=body.bonus_xp_winner,
        facility_id=body.facility_id,
        is_opt_in=body.is_opt_in,
        patient_ids=body.patient_ids,
        group_ids=body.group_ids,
    )
    detail = await challenge_service.get_challenge_detail(
        challenge.challenge_id,
        current_cp.care_provider_id,
    )
    return SuccessResponse(message="Challenge created", data=detail.challenge)


@canonical_router.get(
    "/patients/{patient_id}/gamification/leaderboards/{board_type}",
    response_model=SuccessResponse[LeaderboardResponse],
)
async def canonical_get_leaderboard(
    patient_id: UUID,
    board_type: str,
    scope: str = Query("global"),
    scope_id: Optional[UUID] = Query(None),
    service: LeaderboardService = Depends(get_leaderboard_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    board = await service.get_leaderboard(board_type, scope, pid, scope_id=scope_id)
    return SuccessResponse(message="Leaderboard", data=board)


@canonical_router.get(
    "/patients/{patient_id}/gamification/feed/buddies",
    response_model=SuccessResponse[List[FeedEventResponse]],
)
async def canonical_get_buddy_feed(
    patient_id: UUID,
    service: FeedService = Depends(get_feed_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    feed = await service.get_buddy_feed(pid)
    return SuccessResponse(message="Buddy feed", data=feed)


@canonical_router.post(
    "/patients/{patient_id}/gamification/feed/{feed_event_id}/cheer",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
)
async def canonical_send_cheer(
    patient_id: UUID,
    feed_event_id: UUID,
    body: CheerInput,
    service: FeedService = Depends(get_feed_service),
    actor: Actor = Depends(get_current_actor(**_PATIENT_WRITE_ACTOR)),
    cp_access: CareProviderAccessService = Depends(get_care_provider_access_service),
):
    pid = await _resolve_patient(patient_id, actor, cp_access)
    try:
        await service.send_cheer(pid, feed_event_id, body.reaction.value)
        return SuccessResponse(message="Cheer sent")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@canonical_router.get(
    "/care-providers/{cp_id}/gamification/overview",
    response_model=SuccessResponse[CPGamificationOverview],
)
async def canonical_get_cp_overview(
    cp_id: UUID,
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    if cp_id != current_cp.care_provider_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    overview = await service.get_overview(current_cp.care_provider_id)
    return SuccessResponse(message="Gamification overview", data=overview)


@canonical_router.get(
    "/care-providers/{cp_id}/gamification/at-risk",
    response_model=SuccessResponse[List[PatientEngagementSummary]],
)
async def canonical_get_at_risk(
    cp_id: UUID,
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    if cp_id != current_cp.care_provider_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    patients = await service.get_at_risk_patients(current_cp.care_provider_id)
    return SuccessResponse(message="At-risk patients", data=patients)


@canonical_router.post(
    "/care-providers/{cp_id}/gamification/challenges",
    response_model=SuccessResponse[ChallengeResponse],
    status_code=status.HTTP_201_CREATED,
)
async def canonical_create_cp_challenge(
    cp_id: UUID,
    body: ChallengeCreateInput,
    challenge_service: ChallengeService = Depends(get_challenge_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.CREATE,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    if cp_id != current_cp.care_provider_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    challenge = await challenge_service.create_challenge(
        title=body.title,
        challenge_type=body.challenge_type.value,
        scope=body.scope.value,
        metric_type=body.metric_type.value,
        target_value=body.target_value,
        duration_days=body.duration_days,
        xp_reward=body.xp_reward,
        created_by_id=current_cp.care_provider_id,
        created_by_type="care_provider",
        description=body.description,
        bonus_xp_winner=body.bonus_xp_winner,
        facility_id=body.facility_id,
        is_opt_in=body.is_opt_in,
        patient_ids=body.patient_ids,
        group_ids=body.group_ids,
    )
    detail = await challenge_service.get_challenge_detail(
        challenge.challenge_id, current_cp.care_provider_id
    )
    return SuccessResponse(message="Challenge created", data=detail.challenge)


@canonical_router.post(
    "/care-providers/{cp_id}/gamification/achievements/{achievement_id}/star",
    response_model=SuccessResponse,
)
async def canonical_star_achievement(
    cp_id: UUID,
    achievement_id: UUID,
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.UPDATE,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    if cp_id != current_cp.care_provider_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    await service.star_achievement(current_cp.care_provider_id, achievement_id)
    return SuccessResponse(message="Achievement starred")


@canonical_router.get(
    "/care-providers/{cp_id}/gamification/groups",
    response_model=SuccessResponse[List[GroupResponse]],
)
async def canonical_get_cp_groups(
    cp_id: UUID,
    service: CPGamificationService = Depends(get_cp_gamification_service),
    current_cp: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
        )
    ),
):
    if cp_id != current_cp.care_provider_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    groups = await service.get_groups(current_cp.care_provider_id)
    return SuccessResponse(message="Care provider groups", data=groups)
