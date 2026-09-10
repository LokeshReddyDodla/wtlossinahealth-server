"""DI-graph smoke test — catches broken container factories in CI.

The container registers ~140 singletons with lambda factories; a renamed
constructor kwarg or missing dependency only surfaces at resolve time.
This test resolves every ai_foundation entry point with external
connections (Redis, ClickHouse) mocked at the driver boundary.

Runs in a subprocess so the module-level container singleton (and its
import-time side effects) never leak into other tests' interpreter state.
"""

from __future__ import annotations

import subprocess
import sys

_SMOKE_SCRIPT = """
from unittest.mock import MagicMock, patch

mock_redis = MagicMock()
mock_redis.ping.return_value = True

with patch("redis.from_url", return_value=mock_redis), \\
     patch("clickhouse_driver.Client", return_value=MagicMock()):
    from lib.core.container import container
    from lib.ai_foundation.agents.health_query import HealthQueryAgent
    from lib.ai_foundation.agents.proactive_monitor.agent import ProactiveMonitorAgent
    from lib.ai_foundation.agents.meal_analysis.agent import MealAnalysisAgent
    from lib.ai_foundation.agents.research_agent.agent import ResearchAgent
    from lib.ai_foundation.agents.product_bot.agent import ProductBotAgent
    from lib.ai_foundation.agents.dashboard_help.agent import DashboardHelpAgent
    from lib.ai_foundation.agents.support_assistant.agent import SupportAssistantAgent
    from lib.services.support.support_assistant_service import SupportAssistantService
    from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker
    from lib.ai_foundation.clinical.metabolic import MetabolicService
    from lib.ai_foundation.events.bus import EventBus
    from lib.ai_foundation.memory.mongo_store import MongoMemoryStore
    from lib.ai_foundation.models.gateway import ModelGateway
    from lib.ai_foundation.rate_limit.limiter import RateLimiter
    from lib.ai_foundation.rate_limit.public_limiter import PublicRateLimiter
    from lib.ai_foundation.retrieval.qdrant import QdrantRetriever
    from lib.ai_foundation.voice.stt import BaseSpeechToText
    from lib.ai_foundation.voice.tts import BaseTextToSpeech

    entry_points = [
        ModelGateway,
        EventBus,
        MongoMemoryStore,
        RateLimiter,
        PublicRateLimiter,
        QdrantRetriever,
        InsightTracker,
        MetabolicService,
        HealthQueryAgent,
        ProactiveMonitorAgent,
        MealAnalysisAgent,
        ResearchAgent,
        ProductBotAgent,
        DashboardHelpAgent,
        SupportAssistantAgent,
        SupportAssistantService,
        BaseSpeechToText,
        BaseTextToSpeech,
    ]
    for cls in entry_points:
        obj = container.resolve(cls)
        assert obj is not None, f"{cls.__name__} resolved to None"

    # Singleton scope: resolving twice returns the same instance
    assert container.resolve(HealthQueryAgent) is container.resolve(HealthQueryAgent)

print("WIRING_OK")
"""


def test_container_graph_resolves():
    result = subprocess.run(
        [sys.executable, "-c", _SMOKE_SCRIPT],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"Container wiring smoke failed:\n{result.stderr[-3000:]}"
    )
    assert "WIRING_OK" in result.stdout
