"""Tests for CircuitBreaker — provider failure detection and state machine."""

import time

from lib.ai_foundation.models.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state("openai") == CircuitState.CLOSED
        assert cb.is_available("openai")

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, window_seconds=60)
        cb.record_failure("openai")
        cb.record_failure("openai")
        assert cb.state("openai") == CircuitState.CLOSED
        cb.record_failure("openai")
        assert cb.state("openai") == CircuitState.OPEN
        assert not cb.is_available("openai")

    def test_success_resets_half_open_to_closed(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        cb.record_failure("openai")
        assert cb.state("openai") == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.is_available("openai")  # transitions to HALF_OPEN
        assert cb.state("openai") == CircuitState.HALF_OPEN
        cb.record_success("openai")
        assert cb.state("openai") == CircuitState.CLOSED

    def test_failure_in_half_open_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        cb.record_failure("openai")
        assert cb.state("openai") == CircuitState.OPEN
        time.sleep(0.02)
        cb.is_available("openai")  # transitions to HALF_OPEN
        cb.record_failure("openai")
        assert cb.state("openai") == CircuitState.OPEN

    def test_independent_providers(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("openai")
        cb.record_failure("openai")
        assert cb.state("openai") == CircuitState.OPEN
        assert cb.state("google") == CircuitState.CLOSED
        assert cb.is_available("google")

    def test_stats(self):
        cb = CircuitBreaker(failure_threshold=5, window_seconds=60)
        cb.record_success("openai")
        cb.record_success("openai")
        cb.record_failure("openai")
        stats = cb.get_stats("openai")
        assert len(stats) == 1
        assert stats[0].success_count == 2
        assert stats[0].failure_count == 1
        assert stats[0].state == CircuitState.CLOSED

    def test_get_all_stats(self):
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_success("openai")
        cb.record_success("google")
        stats = cb.get_stats()
        assert len(stats) == 2

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure("openai")
        assert cb.state("openai") == CircuitState.OPEN
        cb.reset("openai")
        assert cb.state("openai") == CircuitState.CLOSED
        assert cb.is_available("openai")

    def test_total_trips(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)
        cb.record_failure("openai")
        assert cb.get_stats("openai")[0].total_trips == 1
        time.sleep(0.02)
        cb.is_available("openai")  # half-open
        cb.record_failure("openai")  # back to open
        assert cb.get_stats("openai")[0].total_trips == 2

    def test_window_expiry(self):
        cb = CircuitBreaker(failure_threshold=3, window_seconds=0.05)
        cb.record_failure("openai")
        cb.record_failure("openai")
        time.sleep(0.06)  # failures expire
        cb.record_failure("openai")
        # Only 1 failure in window, threshold is 3
        assert cb.state("openai") == CircuitState.CLOSED
