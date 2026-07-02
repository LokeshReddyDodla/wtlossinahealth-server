"""Deterministic response checks — no LLM, no flakiness.

Each entry in a case's `checks` uses one of:
    must_mention:      ["148", "spike|rise|rose"]   # every entry; | = any-of
    must_not_mention:  ["stop taking", "discontinue"]
    max_words:         250
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


def run_checks(response: str, checks: dict[str, Any]) -> CheckResult:
    failures: list[str] = []
    lowered = response.lower()

    for entry in checks.get("must_mention", []):
        alternatives = [a.strip().lower() for a in str(entry).split("|")]
        if not any(a in lowered for a in alternatives):
            failures.append(f"must_mention failed: none of {alternatives!r} in response")

    for entry in checks.get("must_not_mention", []):
        alternatives = [a.strip().lower() for a in str(entry).split("|")]
        hits = [a for a in alternatives if a in lowered]
        if hits:
            failures.append(f"must_not_mention failed: found {hits!r}")

    max_words = checks.get("max_words")
    if max_words and len(response.split()) > int(max_words):
        failures.append(f"max_words failed: {len(response.split())} > {max_words}")

    if not response.strip():
        failures.append("empty response")

    return CheckResult(passed=not failures, failures=failures)
