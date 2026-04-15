from pathlib import Path


# tests/gamification/test_smoke_contracts.py → repo root is parents[2]
ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_canonical_router_exposes_planned_gamification_contract():
    source = _read("rest_server/v1/gamification/router.py")

    expected_paths = [
        "/patients/{patient_id}/gamification/profile",
        "/patients/{patient_id}/gamification/streak/freeze",
        "/patients/{patient_id}/gamification/daily",
        "/patients/{patient_id}/gamification/tasks/{task_id}/complete",
        "/patients/{patient_id}/gamification/quests/current",
        "/patients/{patient_id}/gamification/achievements",
        "/patients/{patient_id}/gamification/achievements/recent",
        "/patients/{patient_id}/gamification/buddies",
        "/patients/{patient_id}/gamification/buddies/request",
        "/patients/{patient_id}/gamification/buddies/{buddy_id}/accept",
        "/patients/{patient_id}/gamification/buddies/{buddy_id}",
        "/patients/{patient_id}/gamification/buddies/{buddy_id}/progress",
        "/patients/{patient_id}/gamification/groups",
        "/patients/{patient_id}/gamification/groups/{group_id}",
        "/patients/{patient_id}/gamification/groups/{group_id}/join",
        "/patients/{patient_id}/gamification/groups/{group_id}/leave",
        "/patients/{patient_id}/gamification/groups/{group_id}/members",
        "/patients/{patient_id}/gamification/groups/{group_id}/leaderboard",
        "/patients/{patient_id}/gamification/groups/{group_id}/feed",
        "/patients/{patient_id}/gamification/challenges/available",
        "/patients/{patient_id}/gamification/challenges/active",
        "/patients/{patient_id}/gamification/challenges/{challenge_id}/join",
        "/patients/{patient_id}/gamification/challenges/{challenge_id}/withdraw",
        "/patients/{patient_id}/gamification/challenges/{challenge_id}",
        "/gamification/challenges",
        "/patients/{patient_id}/gamification/challenges/{challenge_id}/leaderboard",
        "/patients/{patient_id}/gamification/leaderboards/{board_type}",
        "/patients/{patient_id}/gamification/feed/{feed_event_id}/cheer",
        "/patients/{patient_id}/gamification/feed/buddies",
        "/care-providers/{cp_id}/gamification/overview",
        "/care-providers/{cp_id}/gamification/at-risk",
        "/care-providers/{cp_id}/gamification/challenges",
        "/care-providers/{cp_id}/gamification/achievements/{achievement_id}/star",
        "/care-providers/{cp_id}/gamification/groups",
    ]

    for path in expected_paths:
        assert path in source


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
