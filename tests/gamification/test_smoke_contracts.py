from pathlib import Path


# tests/gamification/test_smoke_contracts.py → repo root is parents[2]
ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_router_exposes_planned_gamification_contract():
    source = _read("rest_server/v1/gamification/router.py")

    # Patient-scoped reads/writes
    expected_paths = [
        "/patients/{patient_id}/profile",
        "/patients/{patient_id}/streak/freeze",
        "/patients/{patient_id}/daily",
        "/patients/{patient_id}/daily/history",
        "/patients/{patient_id}/tasks/{task_id}/complete",
        "/patients/{patient_id}/quests/current",
        "/patients/{patient_id}/achievements",
        "/patients/{patient_id}/achievements/recent",
        "/patients/{patient_id}/history",
        "/patients/{patient_id}/buddies",
        "/patients/{patient_id}/buddies/search",
        "/patients/{patient_id}/buddies/request",
        "/patients/{patient_id}/buddies/request-by-code",
        "/patients/{patient_id}/buddies/{buddy_id}/accept",
        "/patients/{patient_id}/buddies/{buddy_id}/reject",
        "/patients/{patient_id}/buddies/{buddy_id}",
        "/patients/{patient_id}/buddies/{buddy_id}/progress",
        "/patients/{patient_id}/buddies/by-code/{buddy_code}",
        "/patients/{patient_id}/groups",
        "/patients/{patient_id}/challenges/available",
        "/patients/{patient_id}/challenges/active",
        "/patients/{patient_id}/feed",
        "/patients/{patient_id}/leaderboards/{board_type}",
        # Resource-addressed groups
        "/groups",
        "/groups/by-code/{invite_code}",
        "/groups/{group_id}",
        "/groups/{group_id}/invite-code/rotate",
        "/groups/{group_id}/join",
        "/groups/join-by-code",
        "/groups/{group_id}/leave",
        "/groups/{group_id}/members",
        "/groups/{group_id}/members/{patient_id}",
        "/groups/{group_id}/leaderboard",
        "/groups/{group_id}/feed",
        # Resource-addressed challenges
        "/challenges",
        "/challenges/{challenge_id}",
        "/challenges/{challenge_id}/join",
        "/challenges/{challenge_id}/withdraw",
        "/challenges/{challenge_id}/leaderboard",
        # Feed cheer
        "/feed/{feed_event_id}/cheer",
        # CP scope
        "/care-providers/{cp_id}/overview",
        "/care-providers/{cp_id}/disengaged",
        "/care-providers/{cp_id}/groups",
        "/care-providers/{cp_id}/challenges",
        "/care-providers/{cp_id}/achievements/{achievement_id}/star",
        # Catalog
        "/catalog/achievements",
    ]

    for path in expected_paths:
        assert path in source, f"missing path: {path}"


def test_context_loader_uses_injected_gamification_service():
    source = _read("lib/ai_foundation/agents/core/context_loader.py")

    assert "gamification_service: GamificationService | None = None" in source
    assert "self._gamification_service = gamification_service" in source
    assert "if not patient_id or not self._gamification_service:" in source
    assert "await self._gamification_service.get_gamification_context(" in source


def test_container_registers_context_loader_with_gamification_service():
    source = _read("lib/core/container.py")

    assert "container.register(" in source
    assert "ContextLoader(" in source
    assert "gamification_service=cast(GamificationService, container.resolve(GamificationService))" in source


def test_challenge_service_has_timezone_and_finalization_helpers():
    source = _read("lib/services/gamification/challenge_service.py")

    assert "async def get_finalizable_challenge_ids(" in source
    assert "async def _challenge_patient_ids(" in source
    assert "async def _patient_today(" in source
    assert "await self._patient_today(patient_id, postgres_session)" in source
    assert "local_today(tz_name) > challenge.end_date" in source


def test_leaderboard_refresh_includes_group_monthly_and_challenge_boards():
    source = _read("lib/services/gamification/leaderboard_service.py")

    assert "await self.refresh_monthly_xp_board(" in source
    assert 'scope="group"' in source
    assert 'scope="facility"' in source
    assert "async def refresh_challenge_board(" in source
    assert "await self.refresh_challenge_board(" in source


def test_workers_cover_all_background_jobs():
    cron_source = _read("lib/workers/tasks/gamification/cron.py")
    task_source = _read("lib/workers/tasks/gamification/tasks.py")

    expected_jobs = [
        "process_streaks_for_all",
        "generate_daily_tasks_for_all",
        "evaluate_eod_macros",
        "refresh_leaderboards",
        "process_challenge_lifecycle",
        "cleanup_feed_and_leaderboards",
    ]

    for job in expected_jobs:
        assert job in cron_source
        assert f"async def {job}" in task_source


def test_event_handler_updates_challenge_metrics_from_source_events():
    source = _read("lib/services/gamification/event_handler.py")

    assert 'metric_type="meals_logged"' in source
    assert 'metric_type="workouts"' in source
    assert 'metric_type="steps"' in source
    assert "steps - previous_steps" in source
    assert "async def _increment_challenge_metric(" in source


def test_service_ai_context_includes_group_challenges_and_local_date_helper():
    source = _read("lib/services/gamification/service.py")

    assert "async def get_patient_local_date(" in source
    assert "select(GroupMember.group_id)" in source
    assert "group_challenge_rows" in source
    assert "active_challenges=active_challenges" in source
