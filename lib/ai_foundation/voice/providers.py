"""
Voice Provider Registry — provider-agnostic STT/TTS with fallback routing.

Mirrors the ModelRegistry pattern from models/registry.py: register provider
specs, configure task routes with fallback chains, resolve at call time.

Switching providers is a config change — no code changes required:
    AI_VOICE_STT_PROVIDER=sarvam
    AI_VOICE_TTS_PROVIDER=sarvam
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AudioProvider(str, Enum):
    """Supported audio providers for STT and TTS."""

    OPENAI = "openai"
    SARVAM = "sarvam"


class AudioTask(str, Enum):
    """Audio pipeline tasks — drives provider selection."""

    STT = "stt"
    TTS = "tts"


class AudioProviderSpec(BaseModel):
    """Configuration for a single audio provider."""

    provider: AudioProvider
    model: str = Field(description="Provider-specific model ID.")
    timeout_seconds: float = Field(default=10.0, gt=0)
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific settings (voice, language, format, etc.).",
    )


class AudioTaskRoute(BaseModel):
    """Maps an audio task to a primary provider and ordered fallbacks."""

    primary: str = Field(description="Key in the registry (provider:model).")
    fallbacks: list[str] = Field(default_factory=list)


class AudioProviderRegistry:
    """Central registry for audio providers with fallback chains.

    Thread-safe for reads after initial configuration. Configure at startup,
    then treat as read-only.

    Example::

        registry = AudioProviderRegistry()
        registry.register(AudioProviderSpec(
            provider=AudioProvider.OPENAI, model="whisper-1",
        ))
        registry.register(AudioProviderSpec(
            provider=AudioProvider.SARVAM, model="saaras:v3",
        ))
        registry.set_task_route(
            AudioTask.STT,
            primary="openai:whisper-1",
            fallbacks=["sarvam:saaras:v3"],
        )
        chain = registry.get_fallback_chain(AudioTask.STT)
    """

    def __init__(self) -> None:
        self._specs: dict[str, AudioProviderSpec] = {}
        self._routes: dict[AudioTask, AudioTaskRoute] = {}

    @staticmethod
    def _key(spec: AudioProviderSpec) -> str:
        return f"{spec.provider.value}:{spec.model}"

    def register(self, spec: AudioProviderSpec) -> None:
        self._specs[self._key(spec)] = spec

    def set_task_route(
        self,
        task: AudioTask,
        primary: str,
        fallbacks: list[str] | None = None,
    ) -> None:
        all_keys = [primary, *(fallbacks or [])]
        for key in all_keys:
            if key not in self._specs:
                raise KeyError(
                    f"Cannot route {task.value!r} to unregistered provider {key!r}. "
                    f"Available: {sorted(self._specs.keys())}"
                )
        self._routes[task] = AudioTaskRoute(primary=primary, fallbacks=fallbacks or [])

    def route(self, task: AudioTask) -> AudioProviderSpec:
        route = self._routes.get(task)
        if route is None:
            raise KeyError(f"No route configured for task {task.value!r}.")
        return self._specs[route.primary]

    def get_fallback_chain(self, task: AudioTask) -> list[AudioProviderSpec]:
        route = self._routes.get(task)
        if route is None:
            raise KeyError(f"No route configured for task {task.value!r}.")
        return [self._specs[k] for k in [route.primary, *route.fallbacks]]
