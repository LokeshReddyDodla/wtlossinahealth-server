"""
AI Foundation Configuration — single source of truth for all tunables.

Every configurable value lives here. Code imports from this file, never
hardcodes. Values load from environment variables with sensible defaults.

Usage:
    from lib.ai_foundation.config import settings
    settings.MAX_RECORDS_PER_TYPE  # → 10
    settings.PATIENT_CACHE_TTL     # → 300

To override: set environment variables with AI_ prefix:
    AI_MAX_RECORDS_PER_TYPE=20
    AI_PATIENT_CACHE_TTL=600
    AI_QDRANT_RESULT_LIMIT=50
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class AIFoundationSettings(BaseSettings):
    """All AI Foundation configuration in one place."""

    model_config = {"env_prefix": "AI_", "case_sensitive": False}

    # ── LLM ───────────────────────────────────────────────────────────────

    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key")
    GOOGLE_API_KEY: str = Field(default="", description="Google Gemini API key")

    # ── Retrieval ─────────────────────────────────────────────────────────

    QDRANT_COLLECTION: str = Field(default="patient_data", description="Qdrant collection name")
    QDRANT_RESULT_LIMIT: int = Field(default=30, description="Max results per Qdrant query")
    MAX_RECORDS_PER_TYPE: int = Field(default=10, description="Max records per data_type in LLM context")
    MAX_ANALYSIS_CHARS: int = Field(default=80_000, description="Hard cap on analysis text sent to LLM")

    # ── Cache ─────────────────────────────────────────────────────────────

    PATIENT_CACHE_TTL: int = Field(default=300, description="Patient name/pic cache TTL in seconds")
    SEMANTIC_CACHE_TTL: int = Field(default=900, description="Semantic response cache TTL in seconds")
    EMBEDDING_CACHE_TTL: int = Field(default=86_400, description="Embedding vector cache TTL in seconds")

    # ── Persistence ───────────────────────────────────────────────────────

    TURNS_TTL_DAYS: int = Field(default=90, description="Conversation turns TTL in days")
    SUMMARIES_TTL_DAYS: int = Field(default=90, description="Thread summaries TTL in days")
    TRACES_TTL_DAYS: int = Field(default=30, description="Pipeline traces TTL in days")
    SAMPLES_TTL_DAYS: int = Field(default=180, description="Training samples TTL in days")
    METRICS_TTL_DAYS: int = Field(default=30, description="Agent metrics TTL in days")

    # ── Compaction ────────────────────────────────────────────────────────

    COMPACT_AFTER_TURNS: int = Field(default=4, description="Start compaction after this many turns")
    COMPACT_EVERY_N_TURNS: int = Field(default=2, description="Compact every N turns after threshold")

    # ── Rate Limiting ─────────────────────────────────────────────────────

    RATE_LIMIT_CRITICAL: int = Field(default=10_000, description="Requests/hour for CRITICAL priority")
    RATE_LIMIT_HIGH: int = Field(default=5_000, description="Requests/hour for HIGH priority")
    RATE_LIMIT_NORMAL: int = Field(default=1_000, description="Requests/hour for NORMAL priority")
    RATE_LIMIT_LOW: int = Field(default=500, description="Requests/hour for LOW priority")
    RATE_LIMIT_WINDOW: int = Field(default=3600, description="Rate limit window in seconds")

    # ── Reasoning Engine ──────────────────────────────────────────────────

    REASONING_DEFAULT_TIER: str = Field(default="standard", description="Default reasoning tier: basic, standard, advanced, unlimited")
    REASONING_THINKER_MODEL: str = Field(default="gpt-4.1-mini", description="Model for reasoning/tool decisions")
    REASONING_RESPONDER_MODEL: str = Field(default="gpt-5.1", description="Model for final response generation")
    REASONING_TIMEOUT_SECONDS: float = Field(default=30.0, description="Per-round timeout for thinker LLM calls")
    REASONING_MAX_TOOL_RESULT_CHARS: int = Field(default=2000, description="Max chars per tool result")

    # ── Planning ──────────────────────────────────────────────────────────

    PLANNING_ENABLED: bool = Field(default=True, description="Enable investigation planning for STANDARD+ tiers")
    PLANNING_TIMEOUT_SECONDS: float = Field(default=15.0, description="Timeout for planning LLM call")

    # ── Reflection ────────────────────────────────────────────────────────

    REFLECTION_ENABLED: bool = Field(default=True, description="Enable reflection/critic for ADVANCED+ tiers")
    REFLECTION_MAX_ROUNDS: int = Field(default=2, description="Max reflection rounds for UNLIMITED tier")
    REFLECTION_TIMEOUT_SECONDS: float = Field(default=15.0, description="Timeout for reflection LLM call")

    # ── Multi-Agent ───────────────────────────────────────────────────────

    SPECIALIST_MAX_PARALLEL: int = Field(default=3, description="Max specialists running concurrently")
    SPECIALIST_TIMEOUT_SECONDS: float = Field(default=45.0, description="Timeout for a single specialist investigation")

    # ── Circuit Breaker ───────────────────────────────────────────────────

    CIRCUIT_FAILURE_THRESHOLD: int = Field(default=5, description="Failures before circuit opens")
    CIRCUIT_WINDOW_SECONDS: float = Field(default=60.0, description="Failure counting window")
    CIRCUIT_COOLDOWN_SECONDS: float = Field(default=30.0, description="Cooldown before half-open probe")


# Singleton — import this everywhere
settings = AIFoundationSettings()
