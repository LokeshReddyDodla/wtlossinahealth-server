from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from lib.ai_foundation.agents.core.context_loader import (
    AgentContext,
    ContextLoader,
    build_context_messages,
)
from lib.schemas.gamification import GamificationContext


class TestBuildContextMessages:
    def test_includes_gamification_block(self):
        messages = build_context_messages(
            user_message="How am I doing?",
            system_prompt="system",
            reasoning_prompt="reasoning",
            context=AgentContext(
                local_time="2026-04-03 09:15 IST",
                gamification={
                    "level": 12,
                    "title": "Committed",
                    "total_xp": 5430,
                    "current_streak": 14,
                    "streak_freezes": 2,
                    "recent_achievements": ["streak_14"],
                    "tasks_today": {"completed": 4, "total": 6},
                    "weekly_quest": {"title": "Meal Tracker", "progress": "3/5"},
                    "active_challenges": [{"title": "Group Steps Challenge"}],
                    "buddy_streak": 8,
                },
            ),
        )

        context_messages = [
            m for m in messages if m.get("_meta", {}).get("type") == "context"
        ]

        assert len(context_messages) == 1
        content = context_messages[0]["content"]
        assert "Gamification:" in content
        assert "Level: 12 (Committed)" in content
        assert "Tasks today: 4/6" in content
        assert "Buddy streak: 8" in content


class TestContextLoaderGamification:
    @pytest.mark.asyncio
    async def test_load_includes_gamification_context_and_local_time(
        self,
        monkeypatch,
    ):
        patient_id = "11111111-1111-1111-1111-111111111111"

        memory = AsyncMock()
        memory.get_patient_facts = AsyncMock(return_value=[])
        memory.get_thread_turns = AsyncMock(return_value=[])
        memory.get_thread_summary = AsyncMock(return_value=None)

        resolver = AsyncMock()
        resolver.resolve_names = AsyncMock(return_value={patient_id: "Asha"})
        resolver.resolve_timezones = AsyncMock(
            return_value={patient_id: "Asia/Kolkata"}
        )
        resolver.resolve_language = AsyncMock(return_value="en")

        tracker = AsyncMock()
        tracker.get_history = AsyncMock(return_value=[])

        service = AsyncMock()
        service.get_gamification_context = AsyncMock(
            return_value=GamificationContext(
                level=12,
                title="Committed",
                total_xp=5430,
                current_streak=14,
                streak_multiplier=1.2,
                streak_freezes=2,
                recent_achievements=["streak_14"],
                tasks_today={"completed": 4, "total": 6},
                weekly_quest={"title": "Meal Tracker", "progress": "3/5"},
                active_challenges=[{"title": "Group Steps Challenge"}],
                buddy_streak=8,
            )
        )

        import lib.ai_foundation.agents.core.context_loader as context_loader_module

        monkeypatch.setattr(
            context_loader_module,
            "local_now",
            lambda _tz_name: datetime(
                2026, 4, 3, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata")
            ),
        )

        loader = ContextLoader(
            memory=memory,
            patient_resolver=resolver,
            insight_tracker=tracker,
            gamification_service=service,
        )

        context = await loader.load(
            patient_id=patient_id,
            patient_ids=[patient_id],
            thread_id="thread-1",
        )

        assert context.patient_names == {patient_id: "Asha"}
        assert context.local_time == "2026-04-03 09:15 (Friday) IST"
        assert context.gamification is not None
        assert context.gamification["level"] == 12
        assert context.gamification["tasks_today"] == {"completed": 4, "total": 6}
        service.get_gamification_context.assert_awaited_once()
