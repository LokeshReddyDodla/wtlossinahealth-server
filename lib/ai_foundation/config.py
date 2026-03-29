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

    # ── Retrieval ─────────────────────────────────────────────────────────

    QDRANT_RESULT_LIMIT: int = Field(default=30, description="Max results per Qdrant query")
    MAX_RECORDS_PER_TYPE: int = Field(default=10, description="Max records per data_type in LLM context")
    MAX_ANALYSIS_CHARS: int = Field(default=80_000, description="Hard cap on analysis text sent to LLM")

    # ── Cache ─────────────────────────────────────────────────────────────

    PATIENT_CACHE_TTL: int = Field(default=300, description="Patient name/pic cache TTL in seconds")
    EMBEDDING_CACHE_TTL: int = Field(default=86_400, description="Embedding vector cache TTL in seconds")

    # ── Persistence ───────────────────────────────────────────────────────

    TURNS_TTL_DAYS: int = Field(default=90, description="Conversation turns TTL in days")

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

    # ── Agentic Loop Limits ───────────────────────────────────────────────

    STEP_LOG_TRUNCATION_CHARS: int = Field(default=500, description="Max chars per tool result in reasoning step logs")
    SUMMARY_TRUNCATION_CHARS: int = Field(default=200, description="Max chars for display summaries in SSE events")
    LOOKUP_DEFAULT_LIMIT: int = Field(default=15, description="Default record limit for look_up tool")
    BASELINE_DISPLAY_LIMIT: int = Field(default=20, description="Max individual records shown in compare_baseline")
    MAX_CONTEXT_FACTS: int = Field(default=10, description="Max patient facts included in LLM context")
    MAX_HISTORY_MESSAGES: int = Field(default=8, description="Max conversation history messages in LLM context")
    PROMPT_CACHE_MAX_SIZE: int = Field(default=5, description="Max entries in per-role prompt cache")

    # ── Langfuse Observability ────────────────────────────────────────────

    # Note: Langfuse fields use validation_alias to read LANGFUSE_* (no AI_ prefix)
    # so both LiteLLM and our code read the same env vars.
    LANGFUSE_ENABLED: bool = Field(default=False, description="Enable Langfuse LLM tracing", validation_alias="LANGFUSE_ENABLED")
    LANGFUSE_PUBLIC_KEY: str = Field(default="", description="Langfuse public key", validation_alias="LANGFUSE_PUBLIC_KEY")
    LANGFUSE_SECRET_KEY: str = Field(default="", description="Langfuse secret key", validation_alias="LANGFUSE_SECRET_KEY")
    LANGFUSE_HOST: str = Field(default="http://langfuse-server:3000", description="Langfuse server URL", validation_alias="LANGFUSE_HOST")
    LANGFUSE_PROMPT_CACHE_TTL: int = Field(default=300, description="Langfuse prompt cache TTL in seconds", validation_alias="LANGFUSE_PROMPT_CACHE_TTL")

    # ── Context Window Management ────────────────────────────────────────

    CONTEXT_BUDGET_RATIO: float = Field(default=0.75, description="Fraction of context window to use as input budget")
    CONTEXT_RESPONSE_RESERVE: int = Field(default=4096, description="Minimum tokens reserved for response")
    CONTEXT_WINDOW_DEFAULT: int = Field(default=128_000, description="Default context window if model info unavailable")
    CONTEXT_WINDOW_OVERRIDE: dict[str, int] = Field(default_factory=dict, description="Per-model context window overrides")

    # ── Circuit Breaker ───────────────────────────────────────────────────

    CIRCUIT_FAILURE_THRESHOLD: int = Field(default=5, description="Failures before circuit opens")
    CIRCUIT_WINDOW_SECONDS: float = Field(default=60.0, description="Failure counting window")
    CIRCUIT_COOLDOWN_SECONDS: float = Field(default=30.0, description="Cooldown before half-open probe")


# Singleton — import this everywhere
settings = AIFoundationSettings()
