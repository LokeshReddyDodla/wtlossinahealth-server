"""
Circuit Breaker — detects LLM provider outages and routes to fallbacks.

State machine:

    CLOSED  ──(failures >= threshold in window)──▸  OPEN
    OPEN    ──(cooldown elapsed)─────────────────▸  HALF_OPEN
    HALF_OPEN ──(1 success)──────────────────────▸  CLOSED
    HALF_OPEN ──(1 failure)──────────────────────▸  OPEN

All state is in-memory (fast, no external deps). State resets on process
restart, which is acceptable — the breaker re-learns within seconds.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from enum import Enum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Current state of a circuit for a provider."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitStats(BaseModel):
    """Observable stats for a provider circuit."""

    provider: str
    state: CircuitState
    failure_count: int = Field(default=0, description="Failures in current window.")
    success_count: int = Field(default=0, description="Successes in current window.")
    last_failure_at: float | None = Field(
        default=None, description="Epoch timestamp of last failure."
    )
    last_state_change_at: float | None = Field(
        default=None, description="Epoch timestamp of last state transition."
    )
    total_trips: int = Field(
        default=0, description="Total number of times circuit opened."
    )


class _ProviderCircuit:
    """Internal per-provider state. Guarded by a lock for thread safety."""

    __slots__ = (
        "provider",
        "state",
        "failures",
        "successes",
        "last_failure_at",
        "last_state_change_at",
        "total_trips",
        "_lock",
        "_failure_threshold",
        "_window_seconds",
        "_cooldown_seconds",
    )

    def __init__(
        self,
        provider: str,
        failure_threshold: int,
        window_seconds: float,
        cooldown_seconds: float,
    ) -> None:
        self.provider = provider
        self.state = CircuitState.CLOSED
        self.failures: deque[float] = deque()
        self.successes: deque[float] = deque()
        self.last_failure_at: float | None = None
        self.last_state_change_at: float = time.monotonic()
        self.total_trips: int = 0
        self._lock = threading.Lock()
        self._failure_threshold = failure_threshold
        self._window_seconds = window_seconds
        self._cooldown_seconds = cooldown_seconds

    def _prune_window(self, dq: deque[float], now: float) -> None:
        cutoff = now - self._window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()

    def _transition(self, new_state: CircuitState) -> None:
        old = self.state
        self.state = new_state
        self.last_state_change_at = time.monotonic()
        if new_state == CircuitState.OPEN:
            self.total_trips += 1
        logger.info(
            "Circuit breaker [%s]: %s → %s (trips=%d)",
            self.provider,
            old.value,
            new_state.value,
            self.total_trips,
        )

    def record_success(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune_window(self.successes, now)
            self.successes.append(now)

            if self.state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.CLOSED)
                self.failures.clear()

    def record_failure(self) -> None:
        now = time.monotonic()
        with self._lock:
            self.last_failure_at = now
            self._prune_window(self.failures, now)
            self.failures.append(now)

            if self.state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN)
            elif self.state == CircuitState.CLOSED:
                if len(self.failures) >= self._failure_threshold:
                    self._transition(CircuitState.OPEN)

    def is_available(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                elapsed = now - self.last_state_change_at
                if elapsed >= self._cooldown_seconds:
                    self._transition(CircuitState.HALF_OPEN)
                    return True  # allow one probe request
                return False
            # HALF_OPEN — allow (probe in progress)
            return True

    def get_stats(self) -> CircuitStats:
        now = time.monotonic()
        with self._lock:
            self._prune_window(self.failures, now)
            self._prune_window(self.successes, now)
            return CircuitStats(
                provider=self.provider,
                state=self.state,
                failure_count=len(self.failures),
                success_count=len(self.successes),
                last_failure_at=self.last_failure_at,
                last_state_change_at=self.last_state_change_at,
                total_trips=self.total_trips,
            )


class CircuitBreaker:
    """Manages per-provider circuit breakers.

    Args:
        failure_threshold: Number of failures in the sliding window before
            the circuit opens.
        window_seconds: Duration of the sliding failure window.
        cooldown_seconds: How long to wait in OPEN state before probing.

    Example::

        breaker = CircuitBreaker(failure_threshold=5, window_seconds=60, cooldown_seconds=30)

        if breaker.is_available("openai"):
            try:
                result = await call_openai(...)
                breaker.record_success("openai")
            except ProviderError:
                breaker.record_failure("openai")
        else:
            # use fallback provider
            ...
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        window_seconds: float = 60.0,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._window_seconds = window_seconds
        self._cooldown_seconds = cooldown_seconds
        self._circuits: dict[str, _ProviderCircuit] = {}
        self._lock = threading.Lock()

    def _get_circuit(self, provider: str) -> _ProviderCircuit:
        if provider not in self._circuits:
            with self._lock:
                if provider not in self._circuits:
                    self._circuits[provider] = _ProviderCircuit(
                        provider=provider,
                        failure_threshold=self._failure_threshold,
                        window_seconds=self._window_seconds,
                        cooldown_seconds=self._cooldown_seconds,
                    )
        return self._circuits[provider]

    def record_success(self, provider: str) -> None:
        """Record a successful call to the provider."""
        self._get_circuit(provider).record_success()

    def record_failure(self, provider: str) -> None:
        """Record a failed call to the provider."""
        self._get_circuit(provider).record_failure()

    def is_available(self, provider: str) -> bool:
        """Check if the provider is available (circuit not OPEN)."""
        return self._get_circuit(provider).is_available()

    def state(self, provider: str) -> CircuitState:
        """Return the current circuit state for a provider."""
        return self._get_circuit(provider).state

    def get_stats(self, provider: str | None = None) -> list[CircuitStats]:
        """Return circuit stats for one or all providers."""
        if provider:
            return [self._get_circuit(provider).get_stats()]
        return [c.get_stats() for c in self._circuits.values()]

    def reset(self, provider: str) -> None:
        """Manually reset a provider circuit to CLOSED. Use for recovery."""
        circuit = self._get_circuit(provider)
        with circuit._lock:
            circuit._transition(CircuitState.CLOSED)
            circuit.failures.clear()
