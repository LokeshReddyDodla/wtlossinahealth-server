"""
Proactive Monitor Agent — background health monitoring with push notifications.

Scans patient data on a schedule, detects noteworthy patterns (glucose spikes,
missed meals, inactivity, improving trends), and publishes insights via the
EventBus for notification delivery.
"""

from .agent import ProactiveMonitorAgent
from .contracts import HealthInsight, InsightSeverity, InsightCategory, ScanInsights, ScanResult
from .insight_tracker import InsightTracker

__all__ = [
    "HealthInsight",
    "InsightCategory",
    "InsightSeverity",
    "InsightTracker",
    "ProactiveMonitorAgent",
    "ScanInsights",
    "ScanResult",
]
