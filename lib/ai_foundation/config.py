"""
AI Foundation Configuration — single source of truth for all tunables.

Every configurable value lives here. Code imports from this file, never
hardcodes. Values load from environment variables with sensible defaults.

Usage:
    from lib.ai_foundation.config import settings
    settings.MAX_RECORDS_PER_TYPE  # → 50
    settings.PATIENT_CACHE_TTL     # → 300

To override: set environment variables with AI_ prefix:
    AI_MAX_RECORDS_PER_TYPE=100
    AI_PATIENT_CACHE_TTL=600
    AI_QDRANT_RESULT_LIMIT=200
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class AIFoundationSettings(BaseSettings):
    """All AI Foundation configuration in one place."""

    model_config = {"env_prefix": "AI_", "case_sensitive": False}

    # ── Defaults ─────────────────────────────────────────────────────────

    DEFAULT_PATIENT_TIMEZONE: str = Field(default="Asia/Kolkata", description="Fallback timezone when patient profile has none")

    # ── Retrieval ─────────────────────────────────────────────────────────

    QDRANT_RESULT_LIMIT: int = Field(default=500, description="Safety cap per Qdrant query — retriever paginates up to this limit")
    MAX_RECORDS_PER_TYPE: int = Field(default=200, description="Max records per data_type in LLM context")
    MAX_ANALYSIS_CHARS: int = Field(default=80_000, description="Hard cap on analysis text sent to LLM")

    # ── Cache ─────────────────────────────────────────────────────────────

    PATIENT_CACHE_TTL: int = Field(default=300, description="Patient name/pic cache TTL in seconds")
    EMBEDDING_CACHE_TTL: int = Field(default=86_400, description="Embedding vector cache TTL in seconds")

    # ── Persistence ───────────────────────────────────────────────────────

    TURNS_TTL_DAYS: int = Field(default=90, description="Conversation turns TTL in days")
    SUMMARIES_TTL_DAYS: int = Field(default=90, description="TTL in days for thread summaries")
    PRODUCT_BOT_CONVERSATIONS_TTL_DAYS: int = Field(default=90, description="TTL in days for public product-bot conversation analytics")

    # ── Reasoning Engine ──────────────────────────────────────────────────

    REASONING_DEFAULT_TIER: str = Field(default="standard", description="Default reasoning tier: basic, standard, advanced, unlimited")
    REASONING_THINKER_MODEL: str = Field(default="claude-haiku-4-5-20251001", description="Model for reasoning/tool decisions")
    REASONING_RESPONDER_MODEL: str = Field(default="claude-sonnet-4-6", description="Model for final response generation")
    REASONING_TIMEOUT_SECONDS: float = Field(default=30.0, description="Per-round timeout for thinker LLM calls")
    RESPONDER_TIMEOUT_SECONDS: float = Field(default=60.0, description="Timeout for final response generation (long answers exceed model spec defaults)")
    REASONING_MAX_TOOL_RESULT_CHARS: int = Field(default=16_000, description="Max chars per tool result")
    STREAMING_PIPELINE_TIMEOUT_SECONDS: float = Field(default=90.0, description="End-to-end timeout for the full streaming pipeline")
    PIPELINE_RETRY_BACKOFF_SECONDS: float = Field(default=2.5, description="Backoff before the single silent pipeline retry that precedes any patient-visible error")

    # ── Planning ──────────────────────────────────────────────────────────

    PLANNING_ENABLED: bool = Field(default=True, description="Enable investigation planning for STANDARD+ tiers")
    PLANNING_TIMEOUT_SECONDS: float = Field(default=15.0, description="Timeout for planning LLM call")

    # ── Reflection ────────────────────────────────────────────────────────

    REFLECTION_ENABLED: bool = Field(default=True, description="Enable reflection/critic for ADVANCED+ tiers")
    GROUNDING_VERIFY_ENABLED: bool = Field(default=True, description="Verify the final response against its evidence and correct once if it fabricates, confirms a false claim, or disavows real data")
    REFLECTION_MAX_ROUNDS: int = Field(default=2, description="Max reflection rounds for UNLIMITED tier")
    REFLECTION_TIMEOUT_SECONDS: float = Field(default=15.0, description="Timeout for reflection LLM call")

    REASONING_ADVANCED_THINKER_MODEL: str = Field(default="claude-sonnet-4-6", description="Thinker model for ADVANCED/UNLIMITED tiers")

    # ── Coordinator ──────────────────────────────────────────────────────

    SPECIALIST_TIMEOUT_SECONDS: float = Field(default=120.0, description="Timeout for all specialist investigations in coordinator")

    # ── Agentic Loop Limits ───────────────────────────────────────────────

    STEP_LOG_TRUNCATION_CHARS: int = Field(default=500, description="Max chars per tool result in reasoning step logs")
    SUMMARY_TRUNCATION_CHARS: int = Field(default=200, description="Max chars for display summaries in SSE events")
    LOOKUP_DEFAULT_LIMIT: int = Field(default=200, description="Default record limit for look_up tool")
    METABOLIC_MEAL_HISTORY_LIMIT: int = Field(default=500, description="Max meal records assembled into a metabolic patient state")
    MAX_CONTEXT_FACTS: int = Field(default=10, description="Max patient facts included in LLM context")
    MAX_HISTORY_MESSAGES: int = Field(default=24, description="Max conversation history messages in LLM context — a companion that forgets (and then denies) its own turn-4 advice by turn 12 gaslights the patient; 12 exchanges covers a long session")
    PROMPT_CACHE_MAX_SIZE: int = Field(default=5, description="Max entries in per-role prompt cache")

    # ── Panel (Multi-Patient) Queries ─────────────────────────────────────

    PANEL_LOOKUP_LIMIT: int = Field(default=10, description="Default look_up records per patient in panel queries")
    PANEL_RECORDS_PER_PATIENT: int = Field(default=8, description="Records per patient per data_type in panel queries")
    PANEL_MAX_RECORDS_PER_TYPE: int = Field(default=50, description="Absolute max records per data_type in panel queries")
    PANEL_MAX_TOOL_RESULT_CHARS: int = Field(default=32_000, description="Max chars per tool result for panel (multi-patient) queries")

    # ── Cross-Domain Synthesis ─────────────────────────────────────────────

    CROSS_DOMAIN_SYNTHESIS_ENABLED: bool = Field(default=True, description="Enable LLM cross-domain follow-up in coordinator")
    CROSS_DOMAIN_MAX_TOOL_CALLS: int = Field(default=2, description="Max tool calls in cross-domain synthesis round")

    # ── Conversation Compaction ────────────────────────────────────────────

    COMPACTION_TRIGGER_INTERVAL: int = Field(default=2, description="Compact every N turns after threshold")
    COMPACTION_TRIGGER_THRESHOLD: int = Field(default=4, description="Minimum turns before first compaction")
    COMPACTION_HISTORY_WINDOW: int = Field(default=12, description="Turns to include in summary LLM call")
    BACKGROUND_TASK_TIMEOUT_SECONDS: float = Field(default=30.0, description="Timeout for background tasks (compaction, fact extraction)")

    # ── Memory Compaction ─────────────────────────────────────────────────

    COMPACT_THRESHOLD: int = Field(default=50, description="Compact patient memories when count exceeds this")
    COMPACT_KEEP_RECENT: int = Field(default=5, description="Recent memories to keep per category during compaction")

    # ── Langfuse Observability ────────────────────────────────────────────

    # ── Cohort Agent (openai-agents SDK — runs OUTSIDE ModelGateway, so its
    # model is configured here rather than registry-routed; the registry only
    # routes gateway-called tasks). validation_alias keeps the existing
    # COHORT_AGENT_* env names.
    COHORT_AGENT_MODEL: str = Field(default="gpt-5.2", description="LiteLLM model id for the cohort agent", validation_alias="COHORT_AGENT_MODEL")
    COHORT_AGENT_API_KEY: str = Field(default="", description="Explicit API key override (blank = provider env vars)", validation_alias="COHORT_AGENT_API_KEY")
    COHORT_AGENT_MAX_TURNS: int = Field(default=30, description="Max agent loop turns per cohort query", validation_alias="COHORT_AGENT_MAX_TURNS")
    COHORT_AGENT_API_BASE: str = Field(default="http://localhost:8000", description="Loopback base URL for the agent's internal API calls", validation_alias="COHORT_AGENT_API_BASE")

    # Note: Langfuse fields use validation_alias to read LANGFUSE_* (no AI_ prefix)
    # so both LiteLLM and our code read the same env vars.
    LANGFUSE_ENABLED: bool = Field(default=False, description="Enable Langfuse LLM tracing", validation_alias="LANGFUSE_ENABLED")
    LANGFUSE_PUBLIC_KEY: str = Field(default="", description="Langfuse public key", validation_alias="LANGFUSE_PUBLIC_KEY")
    LANGFUSE_SECRET_KEY: str = Field(default="", description="Langfuse secret key", validation_alias="LANGFUSE_SECRET_KEY")
    LANGFUSE_HOST: str = Field(default="http://langfuse-server:3000", description="Langfuse server URL", validation_alias="LANGFUSE_HOST")
    LANGFUSE_PROMPT_CACHE_TTL: int = Field(default=300, description="Langfuse prompt cache TTL in seconds", validation_alias="LANGFUSE_PROMPT_CACHE_TTL")

    # ── Meal Analysis ─────────────────────────────────────────────────────

    MEAL_HISTORY_DAYS: int = Field(default=30, description="Days of meal history to load for the meal analysis agent")
    MEAL_CGM_EVENT_DAYS: int = Field(default=30, description="Days of CGM events to load for glucose prediction grounding")
    MEAL_WORKOUT_LOOKBACK_HOURS: int = Field(default=24, description="Hours of recent workouts to load for post-workout meal context")
    MEAL_HISTORY_LIMIT: int = Field(default=60, description="Max meal records pulled from Qdrant per preview")
    MEAL_CGM_EVENT_LIMIT: int = Field(default=60, description="Max CGM events pulled from Qdrant per preview")
    MEAL_LLM_TIMEOUT_SECONDS: float = Field(default=45.0, description="Per-call timeout for meal analysis LLM calls (big structured context)")
    MEAL_PROMPT_RECENT_MEALS_LIMIT: int = Field(default=15, description="Max recent meals sent into meal analysis prompts")
    MEAL_PROMPT_CGM_EVENTS_LIMIT: int = Field(default=15, description="Max CGM events sent into meal analysis prompts")

    # ── Metabolic Engine (operational tunables, NOT model calibration) ──

    METABOLIC_ASSEMBLER_CACHE_TTL: int = Field(default=30, description="Assembler patient-state cache TTL in seconds")
    METABOLIC_FOLLOWUP_WINDOW_HOURS: int = Field(default=2, description="Min hours after meal before CGM follow-up")
    METABOLIC_FOLLOWUP_MAX_AGE_DAYS: int = Field(default=7, description="Max days to look back for unfollowed advice")
    METABOLIC_CGM_STALE_DAYS: int = Field(default=2, description="Days after which CGM data triggers a freshness nudge")
    METABOLIC_MAX_NUDGES: int = Field(default=2, description="Max nudges per assessment turn (safety always survives cap)")

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
