"""
Health Query Agent — clean implementation on the AI Foundation.

Conversational health data assistant for patients and care providers.
Understands natural language queries about meals, glucose, fitness,
sleep, vitals, and documents. Returns grounded, evidence-based responses
with native SSE streaming support.
"""

from .agent import HealthQueryAgent
from .contracts import HealthDataType, QueryIntent, QueryResponse

__all__ = [
    "HealthDataType",
    "HealthQueryAgent",
    "QueryIntent",
    "QueryResponse",
]
